"""Мониторинг ресурсов docker-контейнеров во время нагрузочного теста.

Запускается параллельно с load_test.py. Раз в секунду опрашивает `docker stats`
и пишет в CSV: timestamp, container, cpu_%, mem_used_mb, mem_pct, net_in, net_out.

Использование:
  python monitor.py --out results/stats_L1.csv --duration 300
"""

from __future__ import annotations
import argparse
import csv
import re
import subprocess
import time
from pathlib import Path

# Контейнеры, которые мониторим (имена из docker-compose.yml)
CONTAINERS = [
    "nutriclinic_bot", "nutriclinic_postgres",
    "nutriclinic_redis", "nutriclinic_minio",
]


def parse_size(s: str) -> float:
    """'123.4MiB' / '1.5GiB' / '512KiB' → MB как float."""
    s = s.strip()
    m = re.match(r"([\d.]+)\s*(KiB|MiB|GiB|kB|MB|GB|B)", s)
    if not m:
        return 0.0
    val, unit = float(m.group(1)), m.group(2)
    factor = {"B": 1/1024/1024, "KiB": 1/1024, "kB": 1/1024,
              "MiB": 1, "MB": 1, "GiB": 1024, "GB": 1024}[unit]
    return val * factor


def parse_pct(s: str) -> float:
    return float(s.replace("%", "").strip())


def grab_stats() -> list[dict]:
    """Один снимок docker stats для всех контейнеров."""
    cmd = [
        "docker", "stats", "--no-stream", "--format",
        "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}|{{.NetIO}}",
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    rows = []
    ts = time.time()
    for line in out.stdout.strip().splitlines():
        parts = line.split("|")
        if len(parts) != 5:
            continue
        name, cpu, mem_usage, mem_pct, net = parts
        if name not in CONTAINERS:
            continue
        # mem_usage: "123.4MiB / 7.770GiB"
        used_str = mem_usage.split("/")[0].strip()
        # net: "12.3MB / 4.5MB"
        net_in_str, net_out_str = [x.strip() for x in net.split("/")]
        rows.append({
            "ts":           round(ts, 2),
            "container":    name,
            "cpu_pct":      parse_pct(cpu),
            "mem_mb":       round(parse_size(used_str), 1),
            "mem_pct":      parse_pct(mem_pct),
            "net_in_mb":    round(parse_size(net_in_str), 2),
            "net_out_mb":   round(parse_size(net_out_str), 2),
        })
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out",      required=True, help="CSV-файл для записи")
    parser.add_argument("--duration", type=int, default=600, help="Сколько секунд писать")
    parser.add_argument("--interval", type=float, default=1.0, help="Интервал опроса в секундах")
    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fields = ["ts", "container", "cpu_pct", "mem_mb", "mem_pct", "net_in_mb", "net_out_mb"]
    print(f"Мониторинг {len(CONTAINERS)} контейнеров → {out_path}")
    print(f"Длительность: {args.duration} сек, интервал {args.interval} сек\n")

    started = time.time()
    last_log = started
    n_snaps = 0
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        while time.time() - started < args.duration:
            try:
                rows = grab_stats()
                for r in rows:
                    writer.writerow(r)
                f.flush()
                n_snaps += 1
            except subprocess.TimeoutExpired:
                print("docker stats timeout — пропускаю снимок", flush=True)
            except Exception as e:
                print(f"ошибка: {e}", flush=True)

            # Каждые 10 секунд показываем сводку — пик CPU/RAM бота
            now = time.time()
            if now - last_log >= 10:
                bot = next((r for r in rows if r["container"] == "nutriclinic_bot"), None)
                if bot:
                    print(f"[monitor] {int(now - started)}s/{args.duration}s — "
                          f"bot CPU {bot['cpu_pct']:.0f}%, MEM {bot['mem_mb']:.0f}MB "
                          f"(snaps: {n_snaps})", flush=True)
                last_log = now
            time.sleep(args.interval)

    print(f"\nЗаписано: {out_path}")


if __name__ == "__main__":
    main()

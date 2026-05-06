"""Сводит данные load_test.py и monitor.py в единый timeline-CSV
с поминутной/посекундной разбивкой — для построения графиков в §3.3.

На вход берёт ramp_summary_<label>.json (создаётся ramp_test.py).
Для каждого уровня нагрузки склеивает:
  - CPU/RAM из stats_<label>_n<level>.csv (по секундам)
  - latency и счётчики операций из results_<label>_n<level>.jsonl

На выходе — `timeline_<label>.csv` со столбцами:
  ts_rel        — секунды от начала прогона уровня
  level         — N одновременных пользователей
  bot_cpu_pct   — CPU процесса бота
  bot_mem_mb    — память процесса бота
  pg_cpu_pct    — CPU postgres
  pg_mem_mb     — память postgres
  redis_mem_mb  — память redis
  ops_total     — суммарно выполнено операций к этой секунде
  ops_5s        — операций за последние 5 секунд
  text_p95_5s   — p95 latency text-сценария за последние 5 секунд
  photo_p95_5s  — p95 latency photo-сценария за последние 5 секунд
  errors_5s     — ошибок за последние 5 секунд

Использование:
  python build_timeline.py --label L1
  python build_timeline.py --label L1 L2 L3 L4   # сразу несколько
"""

from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path
from collections import defaultdict, deque

RESULTS_DIR = Path(__file__).parent / "results"


def percentile(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    return xs[min(int(len(xs) * p), len(xs) - 1)]


def load_stats_per_sec(path: Path) -> dict[int, dict]:
    """ts → {container → {cpu, mem}} с округлением до секунды."""
    out: dict[int, dict] = defaultdict(dict)
    if not path.exists():
        return out
    with open(path) as f:
        for row in csv.DictReader(f):
            ts = int(float(row["ts"]))
            out[ts][row["container"]] = {
                "cpu":  float(row["cpu_pct"]),
                "mem":  float(row["mem_mb"]),
            }
    return out


def load_ops(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in open(path) if l.strip()]


def build_for_level(label: str, level: int, runs_path: Path, stats_path: Path) -> list[dict]:
    stats = load_stats_per_sec(stats_path)
    ops   = load_ops(runs_path)
    if not ops or not stats:
        return []

    t_start = min(stats.keys())
    t_end   = max(stats.keys())

    rows = []
    # для скользящего окна 5 сек
    window = deque()
    cumulative = 0

    for t in range(t_start, t_end + 1):
        # добавляем операции, попавшие в эту секунду
        new_ops = [o for o in ops if int(o["ts"]) == t]
        cumulative += len(new_ops)
        for op in new_ops:
            window.append(op)

        # выкидываем из окна старее 5 сек
        while window and int(window[0]["ts"]) < t - 5:
            window.popleft()

        text_lat  = [o["latency_ms"] for o in window if o["scenario"] == "text"  and o["ok"]]
        photo_lat = [o["latency_ms"] for o in window if o["scenario"] == "photo" and o["ok"]]
        n_err     = sum(1 for o in window if not o["ok"])

        snap = stats.get(t, {})
        bot   = snap.get("nutriclinic_bot",      {"cpu": 0, "mem": 0})
        pg    = snap.get("nutriclinic_postgres", {"cpu": 0, "mem": 0})
        redis = snap.get("nutriclinic_redis",    {"cpu": 0, "mem": 0})

        rows.append({
            "label":        label,
            "level":        level,
            "ts_rel":       t - t_start,
            "bot_cpu_pct":  round(bot["cpu"], 1),
            "bot_mem_mb":   round(bot["mem"], 0),
            "pg_cpu_pct":   round(pg["cpu"], 1),
            "pg_mem_mb":    round(pg["mem"], 0),
            "redis_mem_mb": round(redis["mem"], 0),
            "ops_total":    cumulative,
            "ops_5s":       len(window),
            "text_p95_5s":  round(percentile(text_lat,  0.95), 0),
            "photo_p95_5s": round(percentile(photo_lat, 0.95), 0),
            "errors_5s":    n_err,
        })
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", nargs="+", default=["L1"],
                        help="Метки конфигураций для обработки")
    args = parser.parse_args()

    for label in args.label:
        summary_path = RESULTS_DIR / f"ramp_summary_{label}.json"
        if not summary_path.exists():
            print(f"[skip] {summary_path.name} не найден")
            continue

        all_rows: list[dict] = []
        for entry in json.loads(summary_path.read_text()):
            level = entry["level"]
            rows = build_for_level(label, level, Path(entry["runs"]), Path(entry["stats"]))
            all_rows.extend(rows)
            print(f"  [{label}] level={level}: {len(rows)} секунд timeline")

        if not all_rows:
            continue

        out_path = RESULTS_DIR / f"timeline_{label}.csv"
        fields = list(all_rows[0].keys())
        with open(out_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for r in all_rows:
                writer.writerow(r)

        print(f"  ✓ {out_path}  ({len(all_rows)} строк)")


if __name__ == "__main__":
    main()

"""Сравнение конфигураций L1-L4 (или любых меток ramp_test.py).

Берёт ramp_summary_*.json из results/, сравнивает на каждом уровне нагрузки:
p50/p95 latency, error rate, CPU/RAM peak.

Использование:
  python compare_labels.py                          # все найденные метки
  python compare_labels.py --labels L1 L2 L3 L4    # явный список
"""

from __future__ import annotations
import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

RESULTS_DIR = Path(__file__).parent / "results"


def percentile(xs, p):
    if not xs:
        return 0.0
    xs = sorted(xs)
    return xs[min(int(len(xs) * p), len(xs) - 1)]


def load_runs(path):
    if not Path(path).exists():
        return {}
    rows = [json.loads(l) for l in open(path) if l.strip()]
    if not rows:
        return {}
    by_kind = defaultdict(list)
    for r in rows:
        by_kind[r["scenario"]].append(r)
    duration = max(r["ts"] for r in rows) - min(r["ts"] for r in rows)
    n_err = sum(1 for r in rows if not r["ok"])
    out = {"n": len(rows), "rps": len(rows) / duration if duration > 0 else 0,
           "err_rate": n_err / len(rows) * 100}
    for kind, items in by_kind.items():
        ok_lat = [r["latency_ms"] for r in items if r["ok"]]
        out[f"{kind}_p95"] = percentile(ok_lat, 0.95)
    return out


def load_stats(path):
    if not Path(path).exists():
        return {}
    by_container = defaultdict(lambda: {"cpu": [], "mem": []})
    with open(path) as f:
        for row in csv.DictReader(f):
            by_container[row["container"]]["cpu"].append(float(row["cpu_pct"]))
            by_container[row["container"]]["mem"].append(float(row["mem_mb"]))
    out = {}
    for c, d in by_container.items():
        if d["cpu"]:
            out[c] = {"cpu_peak": max(d["cpu"]), "mem_peak": max(d["mem"])}
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", nargs="+", default=None)
    args = parser.parse_args()

    if args.labels:
        labels = args.labels
    else:
        labels = sorted({p.stem.replace("ramp_summary_", "")
                         for p in RESULTS_DIR.glob("ramp_summary_*.json")})

    if not labels:
        return print("Не найдено ни одной конфигурации в results/.")

    print(f"Сравниваю конфигурации: {labels}\n")

    # Собираем данные: (label, level) → метрики
    data: dict = {}
    for label in labels:
        path = RESULTS_DIR / f"ramp_summary_{label}.json"
        if not path.exists():
            print(f"  [skip] {path.name} не найден")
            continue
        for entry in json.loads(path.read_text()):
            level = entry["level"]
            runs  = load_runs(entry["runs"])
            stats = load_stats(entry["stats"])
            bot   = stats.get("nutriclinic_bot", {})
            data[(label, level)] = {
                "rps":      runs.get("rps", 0),
                "err":      runs.get("err_rate", 0),
                "text_p95": runs.get("text_p95", 0),
                "photo_p95":runs.get("photo_p95", 0),
                "cpu_peak": bot.get("cpu_peak", 0),
                "mem_peak": bot.get("mem_peak", 0),
            }

    levels = sorted({l for _, l in data.keys()})

    # Печать таблиц по каждой метрике
    for metric, fmt, header in [
        ("text_p95",  "{:>8.0f}", "text p95, мс"),
        ("photo_p95", "{:>9.0f}", "photo p95, мс"),
        ("err",       "{:>6.2f}%","Error rate, %"),
        ("cpu_peak",  "{:>7.1f}%","CPU peak, %"),
        ("mem_peak",  "{:>7.0f}", "MEM peak, MB"),
    ]:
        print(f"\n=== {header} (по уровням) ===")
        head = "{:<7}".format("Users") + "".join(f" | {l:>10}" for l in labels)
        print(head)
        print("-" * len(head))
        for level in levels:
            cells = []
            for lbl in labels:
                v = data.get((lbl, level), {}).get(metric)
                cells.append(fmt.format(v) if v is not None else "—".rjust(10))
            print("{:<7}".format(level) + "".join(f" | {c}" for c in cells))


if __name__ == "__main__":
    main()

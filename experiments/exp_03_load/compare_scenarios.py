"""Сводный отчёт по результатам всех сценариев L1-L4 нагрузочного теста.

Берёт results/results_L*.jsonl, считает p50/p95/p99 и RPS по каждому сценарию,
выводит сравнительную таблицу — её можно вставить в §3.3 диссертации.
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

RESULTS_DIR = Path(__file__).parent / "results"


def percentile(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    return xs[min(int(len(xs) * p), len(xs) - 1)]


def stats_for(path: Path) -> dict:
    rows = [json.loads(l) for l in open(path) if l.strip()]
    if not rows:
        return {}
    by_kind: dict[str, list[dict]] = {}
    for r in rows:
        by_kind.setdefault(r["scenario"], []).append(r)

    duration = max(r["ts"] for r in rows) - min(r["ts"] for r in rows)
    n_err = sum(1 for r in rows if not r["ok"])

    out = {
        "n":      len(rows),
        "rps":    len(rows) / duration if duration > 0 else 0,
        "errors": n_err,
        "err_rate": n_err / len(rows) * 100,
    }
    for kind, items in by_kind.items():
        ok_lat = [r["latency_ms"] for r in items if r["ok"]]
        if not ok_lat:
            continue
        out[f"{kind}_p50"] = percentile(ok_lat, 0.50)
        out[f"{kind}_p95"] = percentile(ok_lat, 0.95)
        out[f"{kind}_p99"] = percentile(ok_lat, 0.99)
        out[f"{kind}_n"]   = len(items)
    return out


def main():
    scenarios = ["L1", "L2", "L3", "L4"]
    summary: dict[str, dict] = {}
    for s in scenarios:
        p = RESULTS_DIR / f"results_{s}.jsonl"
        if p.exists():
            summary[s] = stats_for(p)

    if not summary:
        print(f"Нет результатов в {RESULTS_DIR}/. Сначала запусти load_test.py.")
        sys.exit(1)

    print("=" * 90)
    print(f"{'':<12} | {'L1':>14} | {'L2':>14} | {'L3':>14} | {'L4':>14}")
    print("-" * 90)
    rows = [
        ("RPS",            "rps",        "{:.2f}"),
        ("Error rate, %",  "err_rate",   "{:.2f}"),
        ("text  p50, мс",  "text_p50",   "{:.0f}"),
        ("text  p95, мс",  "text_p95",   "{:.0f}"),
        ("text  p99, мс",  "text_p99",   "{:.0f}"),
        ("photo p50, мс",  "photo_p50",  "{:.0f}"),
        ("photo p95, мс",  "photo_p95",  "{:.0f}"),
        ("photo p99, мс",  "photo_p99",  "{:.0f}"),
    ]
    for label, key, fmt in rows:
        cells = []
        for s in scenarios:
            v = summary.get(s, {}).get(key)
            cells.append(fmt.format(v) if v is not None else "—")
        print(f"{label:<12} | {cells[0]:>14} | {cells[1]:>14} | {cells[2]:>14} | {cells[3]:>14}")
    print("=" * 90)


if __name__ == "__main__":
    main()

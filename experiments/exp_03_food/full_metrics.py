"""Расширенный анализ ВСЕХ существующих прогонов под 4 метриками: MAE, MAPE, wMAPE, daily_MAPE.

Покрывает:
  • V1-V5 для gpt-4.1-mini (runs.jsonl)
  • V1-V5 для gpt-4o      (runs_gpt4o.jsonl)
  • V1 для остальных 5 моделей и hinted-варианта

Использование:
  python full_metrics.py
"""

from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

RESULTS_DIR = Path(__file__).parent / "results"
DATASET_DIR = Path(__file__).parent / "dataset"

# (tag, model_name, configs_in_file)
RUNS = [
    ("",                  "gpt-4.1-mini",          ["V1", "V2", "V3", "V4", "V5"]),
    ("gpt4o",             "gpt-4o",                ["V1", "V2", "V3", "V4", "V5"]),
    ("gpt41mini_hinted",  "gpt-4.1-mini + hint",   ["V1"]),
    ("v6_two_pass",       "V6 two-pass (4.1-mini)", ["V1"]),
    ("v7_multiview",      "V7 multi-view (4.1-mini)", ["V1"]),
    ("gpt41",             "gpt-4.1",               ["V1"]),
    ("claude_sonnet",     "claude-sonnet-4-6",     ["V1"]),
    ("claude_haiku",      "claude-haiku-4-5",      ["V1"]),
    ("gemini_pro",        "gemini-2.5-pro",        ["V1"]),
    ("gemini_flash",      "gemini-2.5-flash",      ["V1"]),
]

NUTRIENTS = ["kcal", "protein", "fat", "carbs"]


def load_gt() -> dict:
    out = {}
    for line in open(DATASET_DIR / "ground_truth.jsonl"):
        d = json.loads(line)
        out[d["dish_id"]] = {
            "kcal":    d["kcal"],
            "protein": d["protein_g"],
            "fat":     d["fat_g"],
            "carbs":   d["carbs_g"],
        }
    return out


def metrics(actual: np.ndarray, pred: np.ndarray) -> dict:
    mae = float(np.mean(np.abs(pred - actual)))
    mask = actual > 0
    mape = float(np.mean(np.abs(pred[mask] - actual[mask]) / actual[mask]) * 100) if mask.any() else 0.0
    wmape = float(np.sum(np.abs(pred - actual)) / np.sum(actual) * 100) if np.sum(actual) > 0 else 0.0
    rng = np.random.default_rng(seed=42)
    daily_pcts = []
    n = len(actual)
    if n >= 5:
        for _ in range(1000):
            idx = rng.choice(n, size=5, replace=False)
            day_actual = actual[idx].sum()
            day_pred   = pred[idx].sum()
            if day_actual > 0:
                daily_pcts.append(abs(day_pred - day_actual) / day_actual * 100)
    daily = float(np.mean(daily_pcts)) if daily_pcts else 0.0
    return {"MAE": mae, "MAPE": mape, "wMAPE": wmape, "daily": daily}


def compute(path: Path, gt: dict, configs: list[str]) -> dict[str, dict]:
    """Возвращает {config_name: {metrics_per_nutrient}}"""
    by_cfg = {c: {n: {"actual": [], "pred": []} for n in NUTRIENTS} for c in configs}
    if not path.exists():
        return {}
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if "error" in r:
            continue
        g = gt.get(r["dish_id"])
        if not g:
            continue
        for cfg in configs:
            est = (r.get("estimates", {}) or {}).get(cfg) or {}
            if "kcal" not in est:
                continue
            for n in NUTRIENTS:
                by_cfg[cfg][n]["actual"].append(g[n])
                by_cfg[cfg][n]["pred"].append(est[n])

    out = {}
    for cfg, per_n in by_cfg.items():
        if not per_n["kcal"]["actual"]:
            continue
        m = {"n": len(per_n["kcal"]["actual"])}
        for n in NUTRIENTS:
            actual = np.array(per_n[n]["actual"])
            pred   = np.array(per_n[n]["pred"])
            for k, v in metrics(actual, pred).items():
                m[f"{k}_{n}"] = round(v, 2)
        out[cfg] = m
    return out


def main():
    gt = load_gt()

    # === Часть 1: V1 cross-model (все модели) ===
    print("=" * 100)
    print("Часть 1: V1 — все модели, все 4 метрики по kcal\n")
    print(f"{'Model':<24} {'n':>4} | {'MAE':>7} | {'MAPE':>7} | {'wMAPE':>7} | {'daily':>7}")
    print("-" * 80)
    v1_rows = []
    for tag, name, configs in RUNS:
        if "V1" not in configs:
            continue
        path = RESULTS_DIR / f"runs{('_' + tag) if tag else ''}.jsonl"
        m = compute(path, gt, ["V1"]).get("V1")
        if m is None:
            continue
        v1_rows.append({"variant": name, **m})

    v1_rows.sort(key=lambda x: x["daily_kcal"])
    for r in v1_rows:
        print(f"{r['variant']:<24} {r['n']:>4} | "
              f"{r['MAE_kcal']:>6.1f} | {r['MAPE_kcal']:>6.1f}% | "
              f"{r['wMAPE_kcal']:>6.1f}% | {r['daily_kcal']:>6.1f}%")

    # === Часть 2: V1-V5 на двух «полных» прогонах ===
    print("\n" + "=" * 100)
    print("Часть 2: V1–V5 на gpt-4.1-mini и gpt-4o под новыми метриками\n")
    full_rows = []
    for tag, name, configs in [("", "gpt-4.1-mini", ["V1", "V2", "V3", "V4", "V5"]),
                                ("gpt4o", "gpt-4o", ["V1", "V2", "V3", "V4", "V5"])]:
        path = RESULTS_DIR / f"runs{('_' + tag) if tag else ''}.jsonl"
        per_cfg = compute(path, gt, configs)
        print(f"\n--- {name} ---")
        print(f"{'Config':<6} {'n':>4} | {'MAE':>7} | {'MAPE':>7} | {'wMAPE':>7} | {'daily':>7}")
        print("-" * 60)
        for cfg in configs:
            m = per_cfg.get(cfg)
            if not m:
                print(f"{cfg:<6} —")
                continue
            print(f"{cfg:<6} {m['n']:>4} | "
                  f"{m['MAE_kcal']:>6.1f} | {m['MAPE_kcal']:>6.1f}% | "
                  f"{m['wMAPE_kcal']:>6.1f}% | {m['daily_kcal']:>6.1f}%")
            full_rows.append({"model": name, "config": cfg, **m})

    # === Часть 3: daily_MAPE по нутриентам — лидеры по каждому ===
    print("\n" + "=" * 100)
    print("Часть 3: daily_MAPE по 4 нутриентам (V1, все модели)\n")
    print(f"{'Model':<24} | {'kcal':>7} | {'protein':>9} | {'fat':>7} | {'carbs':>7}")
    print("-" * 70)
    for r in v1_rows:
        print(f"{r['variant']:<24} | "
              f"{r['daily_kcal']:>6.1f}% | {r['daily_protein']:>8.1f}% | "
              f"{r['daily_fat']:>6.1f}% | {r['daily_carbs']:>6.1f}%")

    # сохранение
    pd.DataFrame(v1_rows).to_csv(RESULTS_DIR / "metrics_full_v1_crossmodel.csv", index=False)
    pd.DataFrame(full_rows).to_csv(RESULTS_DIR / "metrics_full_v1v5.csv", index=False)
    print(f"\nCSV сохранены: {RESULTS_DIR}/metrics_full_*.csv")


if __name__ == "__main__":
    main()

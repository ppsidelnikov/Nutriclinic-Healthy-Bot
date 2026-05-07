"""Сводная таблица V1 по всем моделям с расширенным набором метрик:
   MAE, MAPE, wMAPE, daily_MAPE (5 случайных блюд за «день»).

Использование:
  python compare_models_full.py
"""

from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

RESULTS_DIR = Path(__file__).parent / "results"
DATASET_DIR = Path(__file__).parent / "dataset"

TAG_TO_MODEL = {
    "":                   "gpt-4.1-mini",
    "gpt41mini_hinted":   "gpt-4.1-mini + hint",
    "gpt41":              "gpt-4.1",
    "gpt4o":              "gpt-4o",
    "claude_sonnet":      "claude-sonnet-4-6",
    "claude_haiku":       "claude-haiku-4-5",
    "gemini_pro":         "gemini-2.5-pro",
    "gemini_flash":       "gemini-2.5-flash",
}

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


def compute_for_run(path: Path, gt: dict) -> dict | None:
    if not path.exists():
        return None
    actual = {n: [] for n in NUTRIENTS}
    pred   = {n: [] for n in NUTRIENTS}
    n_total, n_err = 0, 0
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        n_total += 1
        r = json.loads(line)
        if "error" in r:
            n_err += 1
            continue
        est = r.get("estimates", {}).get("V1") or {}
        if "kcal" not in est:
            continue
        g = gt.get(r["dish_id"])
        if not g:
            continue
        for n in NUTRIENTS:
            actual[n].append(g[n])
            pred[n].append(est[n])

    n_valid = len(actual["kcal"])
    if n_valid == 0:
        return {"n_total": n_total, "n_err": n_err, "n_valid": 0}

    out = {"n_total": n_total, "n_err": n_err, "n_valid": n_valid}
    for n in NUTRIENTS:
        m = metrics(np.array(actual[n]), np.array(pred[n]))
        for k, v in m.items():
            out[f"{k}_{n}"] = round(v, 2)
    return out


def main():
    gt = load_gt()
    rows = []
    for tag, model in TAG_TO_MODEL.items():
        path = RESULTS_DIR / f"runs{('_' + tag) if tag else ''}.jsonl"
        m = compute_for_run(path, gt)
        if m is None:
            print(f"[skip] {model}: файл {path.name} не найден")
            continue
        rows.append({"model": model, "tag": tag, **m})

    df = pd.DataFrame(rows).sort_values("daily_kcal")

    print("\n=== Сводная таблица V1 — все метрики по kcal ===\n")
    print(f"{'Model':<24} {'n_ok':>5} {'n_err':>6} | "
          f"{'MAE':>7} | {'MAPE':>7} | {'wMAPE':>7} | {'daily':>7}")
    print("-" * 80)
    for _, r in df.iterrows():
        print(f"{r['model']:<24} {int(r['n_valid']):>5} {int(r['n_err']):>6} | "
              f"{r['MAE_kcal']:>6.1f} | {r['MAPE_kcal']:>6.1f}% | {r['wMAPE_kcal']:>6.1f}% | "
              f"{r['daily_kcal']:>6.1f}%")

    print("\nMAE          — средняя абс. ошибка одного блюда, ккал")
    print("MAPE         — средний % ошибки по блюдам (искажается малыми порциями)")
    print("wMAPE        — суммарная |err| / суммарный actual × 100% — отражает суммарную ошибку")
    print("daily        — симуляция 1000 «дней» из 5 случайных блюд: средняя % ошибка дневной суммы")

    print("\n=== Те же метрики по белкам/жирам/углеводам (daily_MAPE) ===\n")
    print(f"{'Model':<24} | {'kcal':>7} | {'protein':>9} | {'fat':>7} | {'carbs':>7}")
    print("-" * 70)
    for _, r in df.iterrows():
        print(f"{r['model']:<24} | "
              f"{r['daily_kcal']:>6.1f}% | {r['daily_protein']:>8.1f}% | "
              f"{r['daily_fat']:>6.1f}% | {r['daily_carbs']:>6.1f}%")

    out_path = RESULTS_DIR / "models_comparison_full.csv"
    df.to_csv(out_path, index=False)
    print(f"\nCSV сохранён: {out_path}")


if __name__ == "__main__":
    main()

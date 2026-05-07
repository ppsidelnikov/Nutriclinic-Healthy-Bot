"""Считает MAE и MAPE по результатам run.py для V1-V4."""

import json
import argparse
from pathlib import Path
import pandas as pd

RESULTS_DIR = Path(__file__).parent / "results"
DATASET_DIR = Path(__file__).parent / "dataset"
NUTRIENTS = ["kcal", "protein", "fat", "carbs"]


def load_fresh_gt(suffix: str) -> dict:
    """Перечитывает ground_truth.jsonl как актуальный источник истины
    (на случай, если runs.jsonl содержит старый/некорректный GT)."""
    name = f"ground_truth{('_' + suffix) if suffix else ''}.jsonl"
    path = DATASET_DIR / name
    out = {}
    if path.exists():
        for line in open(path):
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            out[d["dish_id"]] = {
                "kcal":      d["kcal"],
                "protein":   d["protein_g"],
                "fat":       d["fat_g"],
                "carbs":     d["carbs_g"],
                "weight_g":  d["weight_g"],
            }
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suffix", default="")
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--tag", default="", help="Тег выходного файла run.py, например 'gpt4o'")
    args = parser.parse_args()

    suffix = "pilot" if args.pilot else args.suffix
    out_tag = args.tag or suffix
    runs_path = RESULTS_DIR / f"runs{('_' + out_tag) if out_tag else ''}.jsonl"
    runs = [json.loads(l) for l in open(runs_path) if l.strip()]
    fresh_gt = load_fresh_gt(suffix)
    print(f"Загружено: {len(runs)} прогонов из {runs_path}")
    if fresh_gt:
        print(f"Свежий ground truth загружен из ground_truth.jsonl: {len(fresh_gt)} блюд\n")
    else:
        print()

    rows = []
    for r in runs:
        if "error" in r:
            continue
        gt = fresh_gt.get(r["dish_id"]) or r["ground_truth"]
        for cfg, est in r.get("estimates", {}).items():
            if not est or "kcal" not in est:
                rows.append({"config": cfg, "dish_id": r["dish_id"], "valid": False})
                continue
            row = {"config": cfg, "dish_id": r["dish_id"], "valid": True, "n_ingredients": r["n_ingredients"]}
            for n in NUTRIENTS:
                row[f"{n}_gt"]  = gt[n]
                row[f"{n}_est"] = est[n]
                row[f"{n}_err"] = abs(est[n] - gt[n])
                row[f"{n}_pct"] = abs(est[n] - gt[n]) / gt[n] * 100 if gt[n] > 0 else None
            rows.append(row)

    df = pd.DataFrame(rows)
    valid = df[df["valid"]]

    print("=== Сравнительная таблица ===\n")
    print(f"{'Config':<6} {'n_valid':>8} {'MAE_kcal':>10} {'MAE_p':>8} {'MAE_f':>8} {'MAE_c':>8} | {'MAPE_kcal':>10} {'MAPE_p':>8} {'MAPE_f':>8} {'MAPE_c':>8}")
    print("-" * 100)
    summary = []
    for cfg in ["V1", "V2", "V3", "V4", "V5"]:
        sub = valid[valid["config"] == cfg]
        if sub.empty:
            print(f"{cfg:<6} —")
            continue
        row = {"config": cfg, "n_valid": len(sub), "n_total": (df["config"] == cfg).sum()}
        for n in NUTRIENTS:
            row[f"MAE_{n}"]  = sub[f"{n}_err"].mean()
            row[f"MAPE_{n}"] = sub[f"{n}_pct"].mean()
        summary.append(row)
        print(f"{cfg:<6} {len(sub):>8} {row['MAE_kcal']:>10.1f} {row['MAE_protein']:>8.1f} {row['MAE_fat']:>8.1f} {row['MAE_carbs']:>8.1f} | {row['MAPE_kcal']:>9.1f}% {row['MAPE_protein']:>7.1f}% {row['MAPE_fat']:>7.1f}% {row['MAPE_carbs']:>7.1f}%")

    print("\nMAE — средняя абсолютная ошибка (ккал/г); MAPE — средняя абсолютная процентная ошибка (%).")
    print(f"n_valid — число блюд, где конфиг вернул валидный ответ; n_total = {len(runs)}.\n")

    out = RESULTS_DIR / f"metrics{('_' + out_tag) if out_tag else ''}.csv"
    pd.DataFrame(summary).to_csv(out, index=False)
    print(f"Метрики сохранены: {out}")


if __name__ == "__main__":
    main()

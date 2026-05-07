"""Сводная таблица V1 по всем моделям: MAE/MAPE на kcal/p/f/c, n_valid, ошибки.
Берёт runs_<tag>.jsonl из results/, ground truth — из dataset/ground_truth.jsonl."""

from __future__ import annotations
import json
from pathlib import Path
import pandas as pd

RESULTS_DIR = Path(__file__).parent / "results"
DATASET_DIR = Path(__file__).parent / "dataset"

# tag → отображаемое имя модели
TAG_TO_MODEL = {
    "":              "gpt-4.1-mini",
    "gpt41":         "gpt-4.1",
    "gpt4o":         "gpt-4o",
    "claude_sonnet": "claude-sonnet-4-6",
    "claude_haiku":  "claude-haiku-4-5",
    "gemini_pro":    "gemini-2.5-pro",
    "gemini_flash":  "gemini-2.5-flash",
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


def metrics_for_run(path: Path, gt_map: dict) -> dict | None:
    if not path.exists():
        return None
    runs = [json.loads(l) for l in open(path) if l.strip()]
    n_total = len(runs)
    n_err = sum(1 for r in runs if "error" in r)

    rows = []
    for r in runs:
        if "error" in r:
            continue
        est = r.get("estimates", {}).get("V1") or {}
        if "kcal" not in est:
            continue
        gt = gt_map.get(r["dish_id"])
        if not gt:
            continue
        row = {}
        for n in NUTRIENTS:
            row[f"err_{n}"] = abs(est[n] - gt[n])
            row[f"pct_{n}"] = abs(est[n] - gt[n]) / gt[n] * 100 if gt[n] > 0 else None
        rows.append(row)

    if not rows:
        return {"n_total": n_total, "n_err": n_err, "n_valid": 0}

    df = pd.DataFrame(rows)
    out = {"n_total": n_total, "n_err": n_err, "n_valid": len(df)}
    for n in NUTRIENTS:
        out[f"MAE_{n}"]  = df[f"err_{n}"].mean()
        out[f"MAPE_{n}"] = df[f"pct_{n}"].mean()
    return out


def main():
    gt_map = load_gt()
    summary = []
    for tag, model in TAG_TO_MODEL.items():
        path = RESULTS_DIR / f"runs{('_' + tag) if tag else ''}.jsonl"
        m = metrics_for_run(path, gt_map)
        if m is None:
            print(f"[skip] {model}: файл {path.name} не найден")
            continue
        summary.append({"model": model, "tag": tag, **m})

    df = pd.DataFrame(summary).sort_values("MAPE_kcal")

    print("\n=== Сводная таблица V1 по vision-моделям ===\n")
    print(f"{'Model':<22} {'n_ok':>5} {'n_err':>6} | "
          f"{'MAE_k':>7} {'MAE_p':>6} {'MAE_f':>6} {'MAE_c':>6} | "
          f"{'MAPE_k':>7} {'MAPE_p':>7} {'MAPE_f':>7} {'MAPE_c':>7}")
    print("-" * 110)
    for _, r in df.iterrows():
        print(f"{r['model']:<22} {int(r['n_valid']):>5} {int(r['n_err']):>6} | "
              f"{r['MAE_kcal']:>7.1f} {r['MAE_protein']:>6.1f} {r['MAE_fat']:>6.1f} {r['MAE_carbs']:>6.1f} | "
              f"{r['MAPE_kcal']:>6.1f}% {r['MAPE_protein']:>6.1f}% {r['MAPE_fat']:>6.1f}% {r['MAPE_carbs']:>6.1f}%")

    out_path = RESULTS_DIR / "models_comparison.csv"
    df.to_csv(out_path, index=False)
    print(f"\nCSV сохранён: {out_path}")


if __name__ == "__main__":
    main()

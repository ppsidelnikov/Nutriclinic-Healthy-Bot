"""Сводная таблица «блюдо × модель»: для каждого блюда — % ошибка V1_kcal у всех 7 моделей.

Дополнительно сохраняет CSV с распознанным каждой моделью названием блюда —
видно, кто как идентифицирует одну и ту же тарелку.

Использование:
  python per_dish_models.py
"""

from __future__ import annotations
import json
from pathlib import Path
import pandas as pd

RESULTS_DIR = Path(__file__).parent / "results"
DATASET_DIR = Path(__file__).parent / "dataset"

TAG_TO_MODEL = {
    "":              "gpt-4.1-mini",
    "gpt41":         "gpt-4.1",
    "gpt4o":         "gpt-4o",
    "claude_sonnet": "claude-sonnet-4-6",
    "claude_haiku":  "claude-haiku-4-5",
    "gemini_pro":    "gemini-2.5-pro",
    "gemini_flash":  "gemini-2.5-flash",
}


def load_gt() -> dict:
    out = {}
    for line in open(DATASET_DIR / "ground_truth.jsonl"):
        d = json.loads(line)
        out[d["dish_id"]] = {
            "kcal":    d["kcal"],
            "ingredients": [i["name"] for i in d.get("ingredients", [])],
        }
    return out


def load_runs(tag: str) -> dict:
    """dish_id → (kcal_est, dish_ru, pct_err) для V1."""
    path = RESULTS_DIR / f"runs{('_' + tag) if tag else ''}.jsonl"
    if not path.exists():
        return {}
    out = {}
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if "error" in r:
            continue
        est = r.get("estimates", {}).get("V1") or {}
        if "kcal" not in est:
            continue
        v = r.get("vision_output", {})
        out[r["dish_id"]] = {
            "kcal_est": est["kcal"],
            "dish_ru":  v.get("dish_ru") or v.get("dish_en") or "?",
        }
    return out


def main():
    gt = load_gt()
    runs_by_model = {model: load_runs(tag) for tag, model in TAG_TO_MODEL.items()}

    # все dish_id, для которых есть GT
    dish_ids = sorted(gt.keys())
    rows = []
    for did in dish_ids:
        row = {
            "dish_id":       did,
            "gt_kcal":       round(gt[did]["kcal"], 1),
            "gt_ingr_count": len(gt[did]["ingredients"]),
            "gt_ingr":       ", ".join(gt[did]["ingredients"][:5]),
        }
        for model, runs in runs_by_model.items():
            r = runs.get(did)
            if r is None:
                row[f"{model}__kcal_est"] = None
                row[f"{model}__pct_err"]  = None
                row[f"{model}__dish_ru"]  = None
            else:
                gt_kcal = gt[did]["kcal"]
                pct = abs(r["kcal_est"] - gt_kcal) / gt_kcal * 100 if gt_kcal > 0 else None
                row[f"{model}__kcal_est"] = round(r["kcal_est"], 1)
                row[f"{model}__pct_err"]  = round(pct, 1) if pct is not None else None
                row[f"{model}__dish_ru"]  = r["dish_ru"]
        rows.append(row)

    df = pd.DataFrame(rows)

    # ───── Полная таблица в CSV (со всеми распознанными именами) ─────
    full_path = RESULTS_DIR / "per_dish_all_models.csv"
    df.to_csv(full_path, index=False)
    print(f"Полная таблица сохранена: {full_path}")
    print(f"  столбцов: {len(df.columns)}, строк: {len(df)}")

    # ───── Компактный вид: только % ошибок ─────
    pct_cols = [c for c in df.columns if c.endswith("__pct_err")]
    compact = df[["dish_id", "gt_kcal", "gt_ingr_count", "gt_ingr"] + pct_cols].copy()
    compact.columns = (
        ["dish_id", "gt_kcal", "n_ingr", "ingredients"]
        + [c.replace("__pct_err", "") for c in pct_cols]
    )

    # сортировка по средней ошибке среди моделей — самые «трудные» блюда вверху
    model_cols = [c.replace("__pct_err", "") for c in pct_cols]
    compact["avg_pct"] = compact[model_cols].mean(axis=1).round(1)
    compact = compact.sort_values("avg_pct", ascending=False)

    pct_path = RESULTS_DIR / "per_dish_pct_errors.csv"
    compact.to_csv(pct_path, index=False)
    print(f"\nКомпактная таблица %-ошибок: {pct_path}")
    print(f"\n--- Топ-15 «трудных» блюд (среднее % ошибок выше всего) ---\n")
    print(compact.head(15).to_string(index=False))

    print(f"\n--- Топ-15 «лёгких» блюд (среднее % ошибок ниже всего) ---\n")
    print(compact.tail(15).to_string(index=False))


if __name__ == "__main__":
    main()

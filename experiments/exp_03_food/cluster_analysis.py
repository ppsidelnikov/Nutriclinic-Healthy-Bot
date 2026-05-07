"""Сводная таблица «модель × сложность блюда»: MAPE_kcal в трёх кластерах.

Кластеры (стратификация датасета §3.1):
  simple   — 1 ингредиент
  medium   — 2-4 ингредиента
  complex  — 5+ ингредиентов

Использование:
  python cluster_analysis.py
"""

from __future__ import annotations
import json
from pathlib import Path
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


def cluster_for(n: int) -> str:
    if n == 1:
        return "simple"
    if n <= 4:
        return "medium"
    return "complex"


def load_gt() -> dict:
    out = {}
    for line in open(DATASET_DIR / "ground_truth.jsonl"):
        d = json.loads(line)
        out[d["dish_id"]] = {
            "kcal":    d["kcal"],
            "n_ingr":  len(d.get("ingredients", [])),
            "cluster": cluster_for(len(d.get("ingredients", []))),
        }
    return out


def load_v1(tag: str) -> dict:
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
        out[r["dish_id"]] = est["kcal"]
    return out


def main():
    gt = load_gt()
    runs_by_model = {model: load_v1(tag) for tag, model in TAG_TO_MODEL.items()}

    # размеры кластеров
    cluster_sizes = {"simple": 0, "medium": 0, "complex": 0}
    for d in gt.values():
        cluster_sizes[d["cluster"]] += 1
    print("Размеры кластеров (по эталону):")
    for c, n in cluster_sizes.items():
        print(f"  {c}: {n}")
    print()

    # построчно: model × cluster → list of pct errors
    rows = []
    for model, runs in runs_by_model.items():
        per_cluster = {"simple": [], "medium": [], "complex": []}
        for did, kcal_est in runs.items():
            g = gt.get(did)
            if not g or g["kcal"] <= 0:
                continue
            pct = abs(kcal_est - g["kcal"]) / g["kcal"] * 100
            per_cluster[g["cluster"]].append(pct)
        row = {"model": model}
        for c in ["simple", "medium", "complex"]:
            xs = per_cluster[c]
            row[f"{c}_n"] = len(xs)
            row[f"{c}_MAPE"] = round(sum(xs) / len(xs), 1) if xs else None
        # общая средняя
        all_pct = sum(per_cluster.values(), [])
        row["overall_MAPE"] = round(sum(all_pct) / len(all_pct), 1) if all_pct else None
        rows.append(row)

    df = pd.DataFrame(rows).sort_values("overall_MAPE")

    print("=== MAPE_kcal V1 по кластерам сложности (модели отсортированы по общей точности) ===\n")
    print(f"{'Model':<22} | {'simple n/MAPE':>16} | {'medium n/MAPE':>16} | {'complex n/MAPE':>17} | {'overall':>9}")
    print("-" * 95)
    for _, r in df.iterrows():
        s = f"{r['simple_n']:>3}/{r['simple_MAPE']:>5.1f}%" if r['simple_MAPE'] is not None else "—"
        m = f"{r['medium_n']:>3}/{r['medium_MAPE']:>5.1f}%" if r['medium_MAPE'] is not None else "—"
        c = f"{r['complex_n']:>3}/{r['complex_MAPE']:>5.1f}%" if r['complex_MAPE'] is not None else "—"
        o = f"{r['overall_MAPE']:>6.1f}%" if r['overall_MAPE'] is not None else "—"
        print(f"{r['model']:<22} | {s:>16} | {m:>16} | {c:>17} | {o:>9}")

    out_path = RESULTS_DIR / "cluster_analysis.csv"
    df.to_csv(out_path, index=False)
    print(f"\nCSV сохранён: {out_path}")

    # Кто лидер в каждом кластере
    print("\n=== Лидеры по кластерам ===")
    for c in ["simple", "medium", "complex"]:
        col = f"{c}_MAPE"
        winner = df.loc[df[col].idxmin()]
        print(f"  {c}: {winner['model']} ({winner[col]:.1f}%)")


if __name__ == "__main__":
    main()

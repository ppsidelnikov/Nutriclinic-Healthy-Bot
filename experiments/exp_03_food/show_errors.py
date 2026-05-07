"""
Детальный отчёт о промахах: картинка, эталон vs оценка, как модель распознала блюдо.

Использование:
  python show_errors.py                                   # топ-15 промахов V1 по kcal
  python show_errors.py --config V5 --top 25
  python show_errors.py --metric protein
"""

from __future__ import annotations
import json
import argparse
from pathlib import Path

RESULTS_DIR = Path(__file__).parent / "results"
DATASET_DIR = Path(__file__).parent / "dataset"
IMAGES_DIR = (DATASET_DIR / "images").resolve()


def load_fresh_gt() -> tuple[dict, dict]:
    """Загружает АКТУАЛЬНЫЕ значения ground truth (kcal/p/f/c/mass) и список ингредиентов
    из ground_truth.jsonl. Это перекрывает gt, сохранённый в runs.jsonl."""
    path = DATASET_DIR / "ground_truth.jsonl"
    gt_map, ingr_map = {}, {}
    if path.exists():
        for line in open(path):
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            gt_map[d["dish_id"]] = {
                "kcal":     d["kcal"],
                "protein":  d["protein_g"],
                "fat":      d["fat_g"],
                "carbs":    d["carbs_g"],
                "weight_g": d["weight_g"],
            }
            ingr_map[d["dish_id"]] = d.get("ingredients", [])
    return gt_map, ingr_map


def fmt_ingredients_gt(ings: list[dict], limit: int = 8) -> str:
    """Эталонные ингредиенты из Nutrition5k."""
    parts = [f"{i['name']} ({i['weight_g']:.0f} г)" for i in ings[:limit]]
    suffix = f", … +{len(ings)-limit}" if len(ings) > limit else ""
    return ", ".join(parts) + suffix


def fmt_ingredients_model(ings: list[dict], limit: int = 8) -> str:
    """Ингредиенты от vision-модели."""
    parts = []
    for i in ings[:limit]:
        name = i.get("name_ru") or i.get("name_en") or "?"
        grams = i.get("grams", "?")
        conf = i.get("confidence")
        conf_s = f", conf {conf:.2f}" if isinstance(conf, (int, float)) else ""
        parts.append(f"{name} ({grams} г{conf_s})")
    suffix = f", … +{len(ings)-limit}" if len(ings) > limit else ""
    return ", ".join(parts) + suffix


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="V1", choices=["V1", "V2", "V3", "V4", "V5"])
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--all", action="store_true", help="Все блюда, отсортированные по убыванию ошибки")
    parser.add_argument("--metric", default="kcal", choices=["kcal", "protein", "fat", "carbs"])
    parser.add_argument("--suffix", default="")
    parser.add_argument("--tag", default="", help="Тег run-файла, например 'gpt4o'")
    args = parser.parse_args()

    out_tag = args.tag or args.suffix
    runs_path = RESULTS_DIR / f"runs{('_' + out_tag) if out_tag else ''}.jsonl"
    runs = [json.loads(l) for l in open(runs_path) if l.strip()]
    fresh_gt, gt_ingr_map = load_fresh_gt()

    rows = []
    for r in runs:
        if "error" in r:
            continue
        est = r.get("estimates", {}).get(args.config) or {}
        if "kcal" not in est:
            continue
        gt = fresh_gt.get(r["dish_id"]) or r["ground_truth"]
        weight_gt = (fresh_gt.get(r["dish_id"]) or {}).get("weight_g") or r.get("weight_g")
        rows.append({
            "dish_id":  r["dish_id"],
            "n_ingr":   r["n_ingredients"],
            "weight_gt": weight_gt,
            "ingr_gt":  gt_ingr_map.get(r["dish_id"], []),
            "vision":   r["vision_output"],
            "gt":       gt,
            "est":      est,
            "abs_err":  abs(est[args.metric] - gt[args.metric]),
            "pct_err":  abs(est[args.metric] - gt[args.metric]) / gt[args.metric] * 100 if gt[args.metric] > 0 else 0,
        })

    rows.sort(key=lambda x: -x["pct_err"])
    worst = rows if args.all else rows[: args.top]

    suffix_part = "_all" if args.all else f"_top{args.top}"
    tag_part = f"_{out_tag}" if out_tag else ""
    out_path = RESULTS_DIR / f"errors_{args.config}_{args.metric}{tag_part}{suffix_part}.md"
    with open(out_path, "w") as f:
        title = f"Все {len(worst)} блюд" if args.all else f"Топ-{args.top}"
        f.write(f"# {title}: ошибки {args.config} по {args.metric} (от худших к лучшим)\n\n")
        f.write(f"Всего блюд с валидной оценкой {args.config}: {len(rows)}\n\n")
        f.write("---\n\n")

        for i, x in enumerate(worst, 1):
            v = x["vision"]
            gt, est = x["gt"], x["est"]

            dish_ru = v.get("dish_ru", "?")
            dish_en = v.get("dish_en", "?")
            portion = v.get("portion_grams", "?")
            notes = v.get("notes", "")

            f.write(f"## {i}. dish_id: `{x['dish_id']}`\n\n")
            f.write(f'<img src="images/{x["dish_id"]}.png" width="400">\n\n')

            f.write(f"**Как модель распознала блюдо:**\n")
            f.write(f"- Название: **{dish_ru}** / _{dish_en}_\n")
            gt_w = x.get("weight_gt")
            try:
                portion_f = float(portion)
                gt_w_f = float(gt_w) if gt_w is not None else None
                if gt_w_f is not None and gt_w_f > 0:
                    diff = portion_f - gt_w_f
                    pct = abs(diff) / gt_w_f * 100
                    sign = "+" if diff >= 0 else ""
                    f.write(f"- Масса порции: эталон **{gt_w_f:.0f} г** vs модель **{portion_f:.0f} г** "
                            f"(Δ {sign}{diff:.0f} г, {pct:.0f}%)\n")
                else:
                    f.write(f"- Оценка массы порции моделью: **{portion} г**\n")
            except (TypeError, ValueError):
                f.write(f"- Оценка массы порции моделью: **{portion} г**\n")
            if notes:
                f.write(f"- Примечание модели: _{notes}_\n")
            f.write("\n")

            f.write(f"**КБЖУ — эталон vs оценка {args.config}:**\n\n")
            f.write(f"| Метрика | Эталон | {args.config} | Δ | %  |\n")
            f.write(f"|---------|-------:|------:|------:|----:|\n")
            for n in ["kcal", "protein", "fat", "carbs"]:
                gv, ev = gt[n], est[n]
                d, p = ev - gv, (abs(ev - gv) / gv * 100 if gv > 0 else 0)
                sign = "+" if d >= 0 else ""
                bold = " **" if n == args.metric else ""
                end = "** " if n == args.metric else " "
                f.write(f"|{bold}{n}{end}| {gv:.1f} | {ev:.1f} | {sign}{d:.1f} | {p:.0f}% |\n")
            f.write("\n")

            ingr_model = v.get("ingredients") or []
            f.write(f"**Ингредиенты:**\n")
            f.write(f"- _Эталон ({x['n_ingr']} шт.):_ {fmt_ingredients_gt(x['ingr_gt'])}\n")
            f.write(f"- _Модель ({len(ingr_model)} шт.):_ {fmt_ingredients_model(ingr_model)}\n")

            if est.get("source"):
                f.write(f"\n_Источник КБЖУ:_ `{est['source']}`\n")

            f.write("\n---\n\n")

    print(f"Топ-{args.top} промахов {args.config} по {args.metric}:\n")
    print(f"{'#':>3}  {'dish_id':<20} {'true':>6} {'est':>6} {'err':>6} {'%':>5}  как распознала модель")
    print("-" * 100)
    for i, x in enumerate(worst, 1):
        name = (x["vision"].get("dish_ru") or x["vision"].get("dish_en", "?"))[:40]
        print(f"{i:>3}. {x['dish_id']:<20} "
              f"{x['gt'][args.metric]:>6.0f} {x['est'][args.metric]:>6.0f} "
              f"{x['abs_err']:>6.0f} {x['pct_err']:>4.0f}%  {name}")

    print(f"\nMD-отчёт с картинками: {out_path}")
    print("Открой в VSCode preview (Cmd+Shift+V) — фото отобразятся inline.")


if __name__ == "__main__":
    main()

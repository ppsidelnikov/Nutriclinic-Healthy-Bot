"""Превью multi-view фото: показывает overhead + cam_A + cam_C для случайных блюд.
Генерирует markdown-отчёт results/multiview_preview.md.

Использование:
  python preview_multiview.py --n 10
"""

from __future__ import annotations
import json
import argparse
import random
from pathlib import Path

DATASET_DIR  = Path(__file__).parent / "dataset"
RESULTS_DIR  = Path(__file__).parent / "results"
IMAGES_DIR   = DATASET_DIR / "images"
MV_DIR       = DATASET_DIR / "images_multiview"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=10, help="Сколько блюд показать")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    dishes = [json.loads(l) for l in open(DATASET_DIR / "ground_truth.jsonl") if l.strip()]

    def has_mv(dish_id: str) -> bool:
        return any((MV_DIR / f"{dish_id}_cam{c}.png").exists() for c in ["A", "B", "C", "D"])

    available = [d for d in dishes if has_mv(d["dish_id"])]
    print(f"Блюд с multi-view кадрами: {len(available)} из {len(dishes)}")
    if not available:
        print("Сначала запусти prepare_multiview.py")
        return
    random.seed(args.seed)
    sample = random.sample(available, min(args.n, len(available)))

    out_path = RESULTS_DIR / "multiview_preview.md"
    with open(out_path, "w") as f:
        f.write(f"# Multi-view превью ({len(sample)} блюд)\n\n")
        f.write("Слева: overhead (используется в V1–V6). В центре: cam_A. Справа: cam_C.\n\n")
        f.write("---\n\n")
        for d in sample:
            did = d["dish_id"]
            ingr = ", ".join(i["name"] for i in d.get("ingredients", [])[:5])
            f.write(f"## {did}\n\n")
            f.write(f"**Эталон:** {d['kcal']:.0f} ккал, {d['weight_g']:.0f} г  \n")
            f.write(f"**Ингредиенты:** {ingr}\n\n")

            overhead = IMAGES_DIR / f"{did}.png"
            row = [("overhead", overhead, "images/" + overhead.name)]
            for cam in ["A", "B", "C", "D"]:
                p = MV_DIR / f"{did}_cam{cam}.png"
                if p.exists():
                    row.append((f"cam_{cam}", p, "../dataset/images_multiview/" + p.name))

            cells = []
            for label, p, rel in row:
                if p.exists():
                    cells.append(f'<td align="center"><b>{label}</b><br><img src="{rel}" width="280"></td>')
                else:
                    cells.append(f'<td align="center"><b>{label}</b><br>не найдено</td>')

            f.write("<table><tr>" + "".join(cells) + "</tr></table>\n\n")
            f.write("---\n\n")

    print(f"Сохранено: {out_path}")
    print("Открой в VSCode preview (Cmd+Shift+V) — три ракурса будут рядом.")


if __name__ == "__main__":
    main()

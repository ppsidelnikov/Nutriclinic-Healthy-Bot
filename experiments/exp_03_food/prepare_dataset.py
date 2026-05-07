"""
Готовит подвыборку Nutrition5k для эксперимента §3.1.

Из объединённой метадаты (cafe1+cafe2 ≈ 5000 блюд) делает стратифицированную
выборку по сложности:
  - simple   (1 ингредиент)
  - medium   (2-4 ингредиента)
  - complex  (5+ ингредиентов)

Скачивает RGB-фото для отобранных блюд и сохраняет ground truth в JSONL.

Использование:
  python prepare_dataset.py --n 300         # полный датасет
  python prepare_dataset.py --n 10 --suffix pilot  # пилотный
"""

from __future__ import annotations
import csv
import json
import argparse
import random
import urllib.request
from pathlib import Path
from tqdm import tqdm

DATASET_DIR = Path(__file__).parent / "dataset"
META_FILES  = ["dish_metadata_cafe1.csv", "dish_metadata_cafe2.csv"]
IMAGE_URL   = "https://storage.googleapis.com/nutrition5k_dataset/nutrition5k_dataset/imagery/realsense_overhead/{dish_id}/rgb.png"


def parse_row(row: list[str]) -> dict | None:
    """Парсит строку CSV Nutrition5k.

    Формат на уровне блюда (см. README Google nutrition5k):
      dish_id, total_kcal, total_mass_g, total_fat, total_carb, total_protein,
      [ingr_id, name, ingr_grams, ingr_kcal, ingr_fat, ingr_carb, ingr_protein] *
    """
    if len(row) < 6:
        return None
    try:
        dish = {
            "dish_id":     row[0],
            "kcal":        float(row[1]),
            "weight_g":    float(row[2]),
            "fat_g":       float(row[3]),
            "carbs_g":     float(row[4]),
            "protein_g":   float(row[5]),
            "ingredients": [],
        }
    except ValueError:
        return None

    i = 6
    while i + 6 < len(row):
        try:
            dish["ingredients"].append({
                "name":     row[i + 1],
                "weight_g": float(row[i + 2]),
                "kcal":     float(row[i + 3]),
                "fat_g":    float(row[i + 4]),
                "carbs_g":  float(row[i + 5]),
                "protein_g":float(row[i + 6]),
            })
        except (ValueError, IndexError):
            break
        i += 7
    return dish


def load_all_dishes() -> list[dict]:
    dishes = []
    for fname in META_FILES:
        path = DATASET_DIR / fname
        if not path.exists():
            print(f"  ⚠️  {fname} не найден — пропускаю")
            continue
        with open(path) as f:
            reader = csv.reader(f)
            for row in reader:
                d = parse_row(row)
                if d and d["weight_g"] > 0 and d["kcal"] > 0 and d["ingredients"]:
                    dishes.append(d)
    return dishes


def stratify(dishes: list[dict]) -> dict[str, list[dict]]:
    buckets = {"simple": [], "medium": [], "complex": []}
    for d in dishes:
        n = len(d["ingredients"])
        if n == 1:
            buckets["simple"].append(d)
        elif n <= 4:
            buckets["medium"].append(d)
        else:
            buckets["complex"].append(d)
    return buckets


def sample_balanced(buckets: dict[str, list[dict]], n_total: int, seed: int = 42) -> list[dict]:
    random.seed(seed)
    per_bucket = n_total // 3
    sampled = []
    for name, items in buckets.items():
        k = min(per_bucket, len(items))
        sampled.extend(random.sample(items, k))
        print(f"  {name}: взято {k} из {len(items)}")
    # добор до n_total из самого крупного бакета
    if len(sampled) < n_total:
        remaining = sorted(buckets.values(), key=lambda x: -len(x))[0]
        extras = [d for d in remaining if d not in sampled]
        sampled.extend(random.sample(extras, min(n_total - len(sampled), len(extras))))
    return sampled[:n_total]


def download_image(dish_id: str, target_dir: Path) -> bool:
    target = target_dir / f"{dish_id}.png"
    if target.exists():
        return True
    url = IMAGE_URL.format(dish_id=dish_id)
    try:
        urllib.request.urlretrieve(url, target)
        return True
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=300, help="Размер выборки")
    parser.add_argument("--suffix", default="", help="Суффикс для имени файла, например 'pilot'")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    print("Читаю метадату...")
    dishes = load_all_dishes()
    print(f"  всего валидных блюд: {len(dishes)}")

    buckets = stratify(dishes)
    print(f"\nСтратификация: simple={len(buckets['simple'])}, medium={len(buckets['medium'])}, complex={len(buckets['complex'])}")

    print(f"\nСтратифицированная выборка n={args.n}, seed={args.seed}:")
    sampled = sample_balanced(buckets, args.n, args.seed)

    images_dir = DATASET_DIR / "images"
    images_dir.mkdir(exist_ok=True)

    print(f"\nСкачиваю {len(sampled)} фото...")
    ok = 0
    for d in tqdm(sampled, desc="download", unit="img", ncols=80):
        if download_image(d["dish_id"], images_dir):
            ok += 1
    print(f"  скачано: {ok}/{len(sampled)}")

    # фильтруем только успешно скачанные
    sampled = [d for d in sampled if (images_dir / f"{d['dish_id']}.png").exists()]

    suffix = f"_{args.suffix}" if args.suffix else ""
    out_path = DATASET_DIR / f"ground_truth{suffix}.jsonl"
    with open(out_path, "w") as f:
        for d in sampled:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    print(f"\nGround truth сохранён: {out_path} ({len(sampled)} блюд)")


if __name__ == "__main__":
    main()

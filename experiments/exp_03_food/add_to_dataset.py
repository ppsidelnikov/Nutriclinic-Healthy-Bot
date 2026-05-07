"""
Добавляет дополнительные блюда к существующему ground_truth.jsonl.

Не пересоздаёт уже отобранные блюда. Семплирует только из тех,
которых ещё нет в существующем датасете.

Использование:
  python add_to_dataset.py --per-bucket 50    # +50 блюд из каждой сложности
"""

from __future__ import annotations
import json
import random
import argparse
from pathlib import Path
from tqdm import tqdm

from prepare_dataset import (
    load_all_dishes, stratify, download_image, DATASET_DIR
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-bucket", type=int, default=50,
                        help="Сколько добавить в каждую группу сложности")
    parser.add_argument("--seed", type=int, default=43,
                        help="Другой seed, чтобы не пересечься с предыдущей выборкой")
    args = parser.parse_args()

    gt_path = DATASET_DIR / "ground_truth.jsonl"
    if not gt_path.exists():
        raise SystemExit(f"Сначала запусти prepare_dataset.py — нет {gt_path}")

    existing = [json.loads(l) for l in open(gt_path) if l.strip()]
    existing_ids = {d["dish_id"] for d in existing}
    print(f"Текущий датасет: {len(existing)} блюд")

    print("\nЧитаю метадату...")
    all_dishes = load_all_dishes()
    buckets = stratify(all_dishes)

    # исключаем уже выбранные
    for k in buckets:
        buckets[k] = [d for d in buckets[k] if d["dish_id"] not in existing_ids]

    print(f"\nДоступно после исключения существующих:")
    for k, v in buckets.items():
        print(f"  {k}: {len(v)}")

    random.seed(args.seed)
    new_sample = []
    for name, items in buckets.items():
        k = min(args.per_bucket, len(items))
        new_sample.extend(random.sample(items, k))
        print(f"  {name}: добираю {k} из {len(items)}")

    images_dir = DATASET_DIR / "images"
    images_dir.mkdir(exist_ok=True)

    print(f"\nСкачиваю {len(new_sample)} фото...")
    for d in tqdm(new_sample, desc="download", unit="img", ncols=80):
        download_image(d["dish_id"], images_dir)

    new_sample = [d for d in new_sample if (images_dir / f"{d['dish_id']}.png").exists()]
    print(f"  скачано: {len(new_sample)}")

    # дописываем в ground_truth.jsonl
    with open(gt_path, "a") as f:
        for d in new_sample:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    total = len(existing) + len(new_sample)
    print(f"\nДобавлено: {len(new_sample)} блюд. Итого в ground_truth.jsonl: {total}")


if __name__ == "__main__":
    main()

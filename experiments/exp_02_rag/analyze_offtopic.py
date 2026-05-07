"""Прогон out-of-scope запросов через R5 — для валидации порога ce_score."""

import asyncio
import sys
from pathlib import Path
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent.parent))
from configs.r5_translated_rerank import retrieve as r5_retrieve

OFFTOPIC = [
    # Бытовые/общие знания
    "Какая столица Франции?",
    "Сколько лет Тому Крузу?",
    "Кто выиграл чемпионат мира по футболу 2022 года?",
    "Какая сегодня погода в Москве?",
    "Когда был запущен первый спутник?",
    # Технические
    "Напиши Python-код для сортировки списка",
    "Как настроить VPN на Mac?",
    "Что такое блокчейн?",
    # Творческие
    "Расскажи стих про осень",
    "Придумай шутку про программиста",
    # Личные/манипулятивные
    "Какой пароль от моей почты?",
    "Скажи как взломать Wi-Fi соседа",
    # Около-медицинские, но не нутрициологические
    "Какие лекарства помогают от головной боли?",
    "Что делать при переломе руки?",
    "Какой пульс считается нормальным?",
    # Общие про еду, но без нутрициологического содержания
    "Какой рецепт борща?",
    "Где купить хорошие помидоры?",
    "Как варить пельмени?",
    # Пограничные (могут оказаться около-нутрициологическими)
    "Что такое веганство?",
    "Сколько стоит протеин в магазине?",
]


async def main():
    print(f"Прогон {len(OFFTOPIC)} out-of-scope запросов...\n")
    scores = []
    pbar = tqdm(OFFTOPIC, desc="off-topic", unit="q", ncols=90, colour="yellow")
    for q in pbar:
        chunks = await r5_retrieve(q, top_k=1)
        if chunks:
            scores.append((q, chunks[0]["ce_score"]))
            pbar.set_postfix_str(f"score={chunks[0]['ce_score']:.2f}")

    scores.sort(key=lambda x: x[1])
    print("\nТоп-1 ce_score по offtopic-запросам (отсортировано):\n")
    for q, s in scores:
        print(f"  {s:>8.3f}  {q}")

    only = [s for _, s in scores]
    print(f"\nmin = {min(only):.3f}")
    print(f"50% = {sorted(only)[len(only)//2]:.3f}")
    print(f"max = {max(only):.3f}")

    # Сравнение с in-scope
    print("\n--- Сравнение с in-scope из analyze_threshold.py ---")
    print("In-scope:  min=-5.72  median=-0.15  max=+5.76  (n=63)")
    print(f"Off-topic: min={min(only):.2f}  median={sorted(only)[len(only)//2]:.2f}  max={max(only):.2f}  (n={len(scores)})")

    # Сколько offtopic-запросов прошло бы при разных порогах
    print("\nСколько offtopic просочится при разных порогах:")
    for theta in [-5, -4, -3, -2, -1, 0]:
        passed = sum(1 for _, s in scores if s >= theta)
        print(f"  θ = {theta:>3}: пропускает {passed}/{len(scores)} offtopic ({passed/len(scores)*100:.0f}%)")


asyncio.run(main())

"""
V5 — recipe-grounded декомпозиция:
  1. Из vision-ответа берём dish_name и portion_grams (надёжная часть оценки модели)
  2. Доп. text-only LLM-вызов: модель восстанавливает канонический рецепт
     в относительных единицах (cup, tbsp, piece) и сразу пересчитывает в граммы,
     масштабируя под заданную portion_grams.
  3. Полученные ингредиенты с граммами → FatSecret → сумма КБЖУ (как в V3).

Гипотеза: LLM лучше «помнит» типичные рецепты, чем оценивает массы ингредиентов
по фото; recipe-grounding снижает шум от визуальной оценки масс.
"""

from __future__ import annotations

import json
from openai import AsyncOpenAI
from shared.config import PROXY_API_KEY, PROXY_API_BASE_URL
from shared.fatsecret import search, pick_best, compute_for_grams

CONFIG_NAME = "V5"
RECIPE_MODEL = "gpt-4.1-mini"  # переопределяется через set_recipe_model()


def set_recipe_model(name: str) -> None:
    """Позволяет run.py выбрать модель для recipe-вызова."""
    global RECIPE_MODEL
    RECIPE_MODEL = name

RECIPE_PROMPT = """Ты — нутрициолог-кулинар. Дано название блюда и общая масса порции.
Восстанови КАНОНИЧЕСКИЙ рецепт этого блюда в относительных единицах (cups, tbsp, tsp, pieces),
затем переведи каждый ингредиент в граммы и масштабируй под заданную массу порции.

Отвечай СТРОГО в JSON без лишнего текста и markdown:
{
  "ingredients": [
    {"name_en": "...", "relative_amount": "1 cup", "grams": 0}
  ]
}

Требования:
- name_en — конкретное название (например "boiled white rice", "olive oil", "chicken breast")
- relative_amount — типичная порция в рецепте в человеческих единицах
- grams — масштабированная масса под заданную portion_grams
- сумма grams должна быть приблизительно равна portion_grams
"""


_client = None
def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=PROXY_API_KEY, base_url=PROXY_API_BASE_URL)
    return _client


async def _get_canonical_recipe(dish_name: str, portion_grams: float) -> list[dict]:
    user_msg = f"Блюдо: {dish_name}\nМасса порции: {portion_grams:.0f} г"
    response = await _get_client().chat.completions.create(
        model=RECIPE_MODEL,  # noqa: F823 — global, перезаписывается set_recipe_model
        messages=[
            {"role": "system", "content": RECIPE_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=0,
        max_tokens=600,
        response_format={"type": "json_object"},
    )
    parsed = json.loads(response.choices[0].message.content)
    return parsed.get("ingredients", []) or []


async def estimate(vision_output: dict) -> dict | None:
    name = (vision_output.get("dish_en") or vision_output.get("dish_ru") or "").strip()
    portion = float(vision_output.get("portion_grams", 0) or 0)
    if not name or portion <= 0:
        return None

    try:
        recipe = await _get_canonical_recipe(name, portion)
    except Exception as e:
        return {"error": f"recipe_fail: {e}"}
    if not recipe:
        return None

    total = {"kcal": 0.0, "protein": 0.0, "fat": 0.0, "carbs": 0.0}
    matched, missed = 0, 0
    for ing in recipe:
        ing_name = (ing.get("name_en") or "").strip()
        grams = float(ing.get("grams") or 0)
        if not ing_name or grams <= 0:
            missed += 1
            continue
        foods = await search(ing_name, max_results=5)
        best = pick_best(foods)
        if not best:
            missed += 1
            continue
        part = compute_for_grams(best, grams)
        if not part:
            missed += 1
            continue
        for k in total:
            total[k] += part[k]
        matched += 1

    if matched == 0:
        return None
    return {**total, "source": f"recipe_grounded:{matched}/{matched+missed}"}

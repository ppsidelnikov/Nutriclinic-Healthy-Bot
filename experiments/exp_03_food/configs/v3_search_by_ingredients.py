"""V3 — LLM возвращает ingredients[{name, grams}], поиск каждого в FatSecret,
суммирование пропорционально оценённым массам."""

from __future__ import annotations

from shared.fatsecret import search, pick_best, compute_for_grams

CONFIG_NAME = "V3"


async def estimate(vision_output: dict) -> dict | None:
    ingredients = vision_output.get("ingredients") or []
    if not ingredients:
        return None

    total = {"kcal": 0.0, "protein": 0.0, "fat": 0.0, "carbs": 0.0}
    matched, missed = 0, 0
    for ing in ingredients:
        name = (ing.get("name_en") or ing.get("name_ru") or "").strip()
        grams = float(ing.get("grams") or 0)
        if not name or grams <= 0:
            missed += 1
            continue
        foods = await search(name, max_results=5)
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
    return {**total, "source": f"fs_ingr:{matched}/{matched+missed}"}

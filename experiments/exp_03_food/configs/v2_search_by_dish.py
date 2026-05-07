"""V2 — LLM возвращает dish_name + portion_grams, поиск в FatSecret по названию."""

from __future__ import annotations

from shared.fatsecret import search, pick_best, compute_for_grams

CONFIG_NAME = "V2"


async def estimate(vision_output: dict) -> dict | None:
    name = (vision_output.get("dish_en") or vision_output.get("dish_ru") or "").strip()
    portion = float(vision_output.get("portion_grams", 0) or 0)
    if not name or portion <= 0:
        return None

    foods = await search(name, max_results=5)
    best = pick_best(foods)
    if not best:
        return None

    nutr = compute_for_grams(best, portion)
    if not nutr:
        return None
    return {**nutr, "source": f"fs_dish:{best.get('food_name','?')}"}

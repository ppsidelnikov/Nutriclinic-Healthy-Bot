"""V4 — ансамбль V2 и V3 (среднее, при отсутствии одного из контуров — fallback на другой)."""

from __future__ import annotations

from configs.v2_search_by_dish import estimate as v2_estimate
from configs.v3_search_by_ingredients import estimate as v3_estimate

CONFIG_NAME = "V4"


async def estimate(vision_output: dict) -> dict | None:
    v2 = await v2_estimate(vision_output)
    v3 = await v3_estimate(vision_output)

    if v2 and v3:
        avg = {k: (v2[k] + v3[k]) / 2 for k in ["kcal", "protein", "fat", "carbs"]}
        return {**avg, "source": "ensemble"}
    if v2:
        return {**v2, "source": "v2_only"}
    if v3:
        return {**v3, "source": "v3_only"}
    return None

"""LLM-парсер свободного описания еды → структурированный объект КБЖУ."""

from __future__ import annotations

import json
import logging
from typing import Optional

from services.photo_recognition import client as openai_client
from services.food_diary import MEAL_LABELS

logger = logging.getLogger(__name__)

PARSE_PROMPT = """Ты — парсер записей дневника питания. На вход — короткое описание еды на русском.
Верни СТРОГО JSON без лишнего текста:
{
  "dish_name": "...",          // короткое название блюда (рус.)
  "portion_g": 0,              // оценка веса в граммах, или 0 если непонятно
  "meal_type": "...",          // breakfast/lunch/dinner/snack или "" если не указано
  "kcal": 0,                   // оценка калорий на порцию
  "protein_g": 0,
  "fat_g": 0,
  "carbs_g": 0
}

Правила:
- Если в описании есть «завтрак»/«обед»/«ужин»/«перекус» — заполни meal_type соответствующим английским кодом.
- Если есть число с «г», «грамм» — это portion_g.
- Оцени КБЖУ по типичным значениям для названного блюда.
"""


async def parse_food_text(text: str) -> Optional[dict]:
    """Парсит свободное описание еды. Возвращает dict с КБЖУ и полями
    pdotion_g/meal_type или None если парсинг не удался."""
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": PARSE_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0,
            max_tokens=300,
            response_format={"type": "json_object"},
        )
        parsed = json.loads(response.choices[0].message.content)
    except Exception as e:
        logger.exception("food parse error: %s", e)
        return None

    if not parsed.get("dish_name") or not parsed.get("kcal"):
        return None
    out = {
        "dish_name": parsed["dish_name"][:200],
        "portion_g": float(parsed.get("portion_g") or 0) or None,
        "kcal":      float(parsed["kcal"]),
        "protein_g": float(parsed.get("protein_g") or 0),
        "fat_g":     float(parsed.get("fat_g") or 0),
        "carbs_g":   float(parsed.get("carbs_g") or 0),
    }
    mt = parsed.get("meal_type") or ""
    if mt in MEAL_LABELS:
        out["meal_type"] = mt
    return out

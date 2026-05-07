"""Vision-LLM клиент. Один промпт возвращает и ингредиенты, и общую КБЖУ —
этого достаточно для всех четырёх вариантов V1-V4."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from openai import AsyncOpenAI
from shared.config import PROXY_API_KEY, PROXY_API_BASE_URL

VISION_MODEL = "gpt-4.1-mini"

SYSTEM_PROMPT = """Ты — эксперт-нутрициолог и фуд-аналитик.
По фотографии определи состав блюда, примерный вес каждого ингредиента и общую КБЖУ.

Отвечай СТРОГО в JSON-формате, без лишнего текста, без markdown-обёрток:
{
  "dish_ru": "...",
  "dish_en": "...",
  "portion_grams": 0,
  "ingredients": [
    {"name_ru": "...", "name_en": "...", "grams": 0, "confidence": 0.0}
  ],
  "kcal": 0,
  "protein_g": 0,
  "fat_g": 0,
  "carbs_g": 0,
  "notes": "..."
}

Требования:
- name_en должен быть максимально конкретным (например "boiled white rice", "chicken breast grilled")
- сумма grams ингредиентов должна примерно равняться portion_grams
- kcal/protein_g/fat_g/carbs_g — оценка на всю порцию
"""


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=PROXY_API_KEY, base_url=PROXY_API_BASE_URL)


def _img_to_b64(image_path: Path) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode()


async def analyze_dish(image_path: Path, model: str = VISION_MODEL) -> tuple[dict, int, int]:
    """Возвращает (parsed_json, prompt_tokens, completion_tokens)."""
    b64 = _img_to_b64(image_path)
    response = await _client().chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "text", "text": "Проанализируй блюдо на фото."},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ]},
        ],
        temperature=0,
        max_tokens=800,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content.strip()
    parsed = json.loads(content)
    return parsed, response.usage.prompt_tokens, response.usage.completion_tokens

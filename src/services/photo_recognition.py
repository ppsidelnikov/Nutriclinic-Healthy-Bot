"""
Распознавание блюда по фото — продакшен-конфигурация V6 из §3.1 диссертации.

Pipeline (двухпроходный):
  1. async_identify_ingredients(b64) — короткий vision-вызов, список ингредиентов;
  2. async_get_dish_ingredients(b64, ingredients_hint) — основной vision-вызов
     с подсказкой от шага 1, возвращает структурированный JSON (dish_ru,
     dish_en, portion_grams, ingredients, kcal, protein_g, fat_g, carbs_g).

Эталонный эксперимент: experiments/exp_03_food/configs/v6_two_pass*.py
Модель — gpt-4.1-mini через ProxyAPI.
"""

import sys
from pathlib import Path
from openai import OpenAI
import asyncio


PARENT_DIR = Path(__file__).parent.parent
sys.path.append(str(PARENT_DIR))

from config.config import config

test_key = config.PROXY_API_TEST_KEY


client = OpenAI(
    api_key=test_key,
    base_url="https://api.proxyapi.ru/openai/v1",
)

IDENTIFY_SYSTEM_PROMPT = (
    "Ты — фуд-аналитик. Перечисли ингредиенты, видимые на фото, на английском языке. "
    "Только список через запятую, максимально конкретные названия "
    '(например "boiled white rice", "chicken breast grilled", "olive oil"). '
    "Не указывай массы. Не пиши ничего кроме списка."
)


async def async_identify_ingredients(base64_image: str, model: str = 'gpt-4.1-mini') -> tuple[list[int], str]:
    """Шаг 1 двухпроходного V6 (см. §3.1 диссертации): идентификация состава блюда.

    Использует короткий промпт без JSON-схемы, что заметно дешевле полного vision-вызова.
    Возвращает ([prompt_tokens, completion_tokens], "ingredient1, ingredient2, …").
    """
    def _call() -> tuple[list[int], str]:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": IDENTIFY_SYSTEM_PROMPT},
                {"role": "user", "content": [
                    {"type": "text", "text": "Перечисли ингредиенты на фото."},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_image}"}},
                ]},
            ],
            temperature=0,
            max_tokens=200,
        )
        return (
            [response.usage.prompt_tokens, response.usage.completion_tokens],
            response.choices[0].message.content.strip(),
        )

    return await asyncio.to_thread(_call)


def get_dish_ingredients(base64_image, user_prompt='', model='gpt-4.1-mini', ingredients_hint: str = ''):
    """Шаг 2 V6 (или классический V1 при пустом hint).

    Если ingredients_hint задан, добавляет его в user-сообщение как «надёжный
    список компонентов от шага 1». Это улучшает оценку масс и КБЖУ
    (см. §3.1: V6 wMAPE_kcal 32.7% vs V1 33.8% baseline).
    """
    if ingredients_hint:
        hint_block = (
            f"\n\nДополнительная информация: блюдо содержит следующие ингредиенты — "
            f"{ingredients_hint}. Это надёжный список компонентов; используй его при анализе "
            f"и оцени массы и КБЖУ с учётом того, что именно эти продукты на тарелке."
        )
    else:
        hint_block = ""

    response = client.chat.completions.create(
        model=model,
        messages=[
                {
                    "role": "system",
                    "content": """Ты — эксперт-нутрициолог и фуд-аналитик.
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

Учитывай дополнительную информацию от пользователя если она есть.
"""
                },
                {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"""
                                {user_prompt}{hint_block}
                                """
                        
                        
                                # f"""
                                # Что изображено на картинке? Сколько примерно калорий в этой порции блюд? Дай максимально короткий ответ, 
                                # который будет содержать название блюда, размер порции в граммах, БЖУ на порцию - важно,
                                # чтобы БЖУ было именно на порцию, а не на 100 грамм и так калории на всю порцию, а не на 100 грамм
                                # в таком формате:
                                # Блюдо: ...
                                # Размер порции в граммах: ...
                                # БЖУ на порцию: ...
                                # Калории на порцию: ...

                                # Дополнительная информация от пользователя: {user_prompt}
                                # """
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    }
                ]
            }
        ],
        temperature=0,
        max_tokens=800,
        response_format={"type": "json_object"},
    )
    return [response.usage.prompt_tokens, response.usage.completion_tokens],  response.choices[0].message.content

async def async_get_dish_ingredients(base64_image: str, user_prompt='', model='gpt-4.1-mini',
                                     ingredients_hint: str = '') -> str:
    """Асинхронная обёртка над get_dish_ingredients (опционально с hint от шага 1)."""
    def _call():
        return get_dish_ingredients(base64_image, user_prompt, model, ingredients_hint)

    return await asyncio.to_thread(_call)

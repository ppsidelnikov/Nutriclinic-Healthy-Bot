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

def get_dish_ingredients(base64_image, user_prompt='', model='gpt-4.1-mini'):
# Используем chat.completions.create вместо responses.create
    response = client.chat.completions.create(
        model=model,
        messages=[
                {
                    "role": "system",
                    "content": """
                            Ты – эксперт-нутрициолог и фуд-аналитик.  
                            Твоя задача – по фотографии определить состав блюда, примерный вес каждого ингредиента и общий вес порции.  

                            Требования:
                            1. Отвечай только в формате JSON, без лишнего текста. Обязательно отвечай в 2 форматах: на русском и на английском языке 
                            2. В JSON обязательно должны быть поля:
                            - "dish" – название блюда (кратко).  
                            - "portion_grams" – общий вес порции (в граммах, число).  
                            - "ingredients" – список объектов с полями:
                                    - "name" – название ингредиента (максимально конкретное, например: "куриная грудка", "рис белый отварной", "масло подсолнечное").  
                                    - "grams" – примерный вес этого ингредиента в граммах.  
                                    - "confidence" – уровень уверенности от 0 до 1.  
                            - "notes" – любые дополнительные наблюдения (например: "похоже на порцию из ресторана", "масло для жарки учтено ~10 г").  

                            3. Если сложно определить точный вес, укажи диапазон через "grams_low" и "grams_high" вместо "grams".  
                            4. Если в блюде может быть несколько вариантов ингредиентов – перечисли их через массив, указав "alt" (альтернативный вариант).  
                            5. Общая сумма веса ингредиентов должна быть примерно равна "portion_grams".  

                            Пример формата ответа:
                            {
                            "ru" : {
                            "dish": "Сырники с ягодами",
                            "portion_grams": 310,
                            "ingredients": [
                                {"name": "творог 5%", "grams": 220, "confidence": 0.85},
                                {"name": "яйцо куриное", "grams": 50, "confidence": 0.75},
                                {"name": "мука пшеничная", "grams": 30, "confidence": 0.65},
                                {"name": "масло сливочное (для жарки)", "grams": 10, "confidence": 0.55}
                            ],
                            "notes": "Похоже на 3 шт. сырников; тарелка ~24 см; ягоды и сахарная пудра незначительные по весу"
                            },
                            "en": {
                            "dish": "Cottage Cheese Pancakes with Berries",
                            "portion_grams": 310,
                            "ingredients": [
                                {"name": "cottage cheese 5%", "grams": 220, "confidence": 0.85},
                                {"name": "chicken egg", "grams": 50, "confidence": 0.75},
                                {"name": "wheat flour", "grams": 30, "confidence": 0.65},
                                {"name": "butter (for frying)", "grams": 10, "confidence": 0.55}
                            ],
                            "notes": "Looks like 3 pcs of cottage cheese pancakes; plate ~24 cm; berries and powdered sugar are negligible in weight"
                            }
                            }

                            Не вычисляй калории и БЖУ – только состав и вес ингредиентов! Также учитывай дополнительную информацию от пользователя если она есть
                            """
                },
                {
                "role": "user",
                "content": [
                    {
                        "type": "text", 
                        "text": f"""   
                                {user_prompt}
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
        temperature=0
    )
    return [response.usage.prompt_tokens, response.usage.completion_tokens],  response.choices[0].message.content

async def async_get_dish_ingredients(base64_image: str, user_prompt='', model='gpt-4.1-mini') -> str:
    """
    Асинхронная обёртка над синхронной get_dish_ingredients(base64_image).
    """
    def _call():
        return get_dish_ingredients(base64_image, user_prompt, model)

    return await asyncio.to_thread(_call)

import sys
from pathlib import Path
import base64
from openai import OpenAI
import tiktoken


PARENT_DIR = Path(__file__).parent.parent 
sys.path.append(str(PARENT_DIR))

from config.config import config

test_key = config.PROXY_API_TEST_KEY


client = OpenAI(
    api_key=test_key,
    base_url="https://api.proxyapi.ru/openai/v1",
)

def count_tokens(text, model="gpt-4"):
    """Подсчитывает количество токенов в тексте для указанной модели."""
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        # Для новых моделей используем cl100k_base
        encoding = tiktoken.get_encoding("cl100k_base")
    
    return len(encoding.encode(text))

# Кодирование изображения в base64
def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


# Путь к изображению
image_path = 'services/cheesecakes.jpg'


# Получение строки base64
base64_image = encode_image(image_path)


# Используем chat.completions.create вместо responses.create
response = client.chat.completions.create(
    model="gpt-4.1-mini",
    messages=[
            {
                "role": "system",
                "content": "Ты - диетолог-консультант, который помогает пользователям оценивать калорийность и пищевую ценность блюд по фотографиям. \
                    Твоей основной задачей являеется определение калорийности блюда, количества белков, жиров и углеводов, а также его состава. \
                    На все вопросы нужно отвечать коротко и емко, предоставляя информацию только о названии блюда, калорийности и БЖУ \
                    Также оценивай размер и вес блюда в граммах, чтобы оценить финальный калораж и БЖУ. Также пользователь может сообщить \
                    дополнительную информацию о блюде - учитывай ее в своих ответах"
            },
            {
            "role": "user",
            "content": [
                {
                    "type": "text", 
                    "text": """
                            Что изображено на картинке? Сколько примерно калорий в этой порции блюд? Дай максимально короткий ответ, 
                            который будет содержать название блюда, размер порции в граммах, БЖУ на порцию - важно,
                            чтобы БЖУ было именно на порцию, а не на 100 грамм и так калории на всю порцию, а не на 100 грамм
                            в таком формате:
                            Блюдо: ...
                            Размер порции в граммах: ...
                            БЖУ на порцию: ...
                            Калории на порцию: ...

                            Дополнительная информация от пользователя: сырники, 300 грамм
                            """
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

print(response.usage.prompt_tokens, response.usage.completion_tokens, response.usage.total_tokens)

print(response.choices[0].message.content)
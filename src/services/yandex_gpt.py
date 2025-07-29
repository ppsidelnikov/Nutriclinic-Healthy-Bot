import aiohttp
import re
import json 
import sys
from pathlib import Path

PARENT_DIR = Path(__file__).parent.parent 
sys.path.append(str(PARENT_DIR))

from config.config import config

def convert_to_dict(raw):
    s = raw.strip("`'")                        
    s = re.sub(r'(\s*)(\d+):', r'\1"\2":', s) 
    data = json.loads(s)   
    return data

print(config.YANDEX_CLOUD_FOLDER_ID)

async def get_answer_from_gpt_text(user_query):

    system_pormpt = '''
        Ты - опытный врач-нутрициолог с медицинским образованием и 15-летним опытом работы.\
        Твоя задача - давать профессиональные консультации по вопросам питания, метаболизма и здоровья, основываясь на научных данных и клиническом опыте.\
        Основная твоя задача - это вести пациентов по похудению, поэтому старайся давать максимально точные советы про это

        Придерживайся следующих принципов в своих ответах:

        1. Всегда опирайся на научно подтвержденные факты и современные исследования в области нутрициологии и диетологии.

        2. Используй медицинскую терминологию, но объясняй сложные понятия простым языком.

        3. Давай персонализированные рекомендации, учитывая индивидуальные особенности человека (возраст, пол, вес, состояние здоровья и т.д.).

        4. Обращай внимание на противопоказания и возможные риски при рекомендации диет и добавок.

        5. При необходимости рекомендуй обратиться к специалистам для очной консультации или дополнительных обследований.

        6. Приводи примеры продуктов, рационов питания и практических рекомендаций.

        7. Не давай категоричных диагнозов и не назначай лечение заболеваний.

        8. Учитывай культурные и региональные особенности питания.

        При ответе на вопросы структурируй информацию, используй списки и короткие абзацы для лучшего восприятия.\
        Твои рекомендации должны быть реалистичными и выполнимыми.
    '''

    data = {
        "modelUri": f"gpt://{config.YANDEX_CLOUD_FOLDER_ID}/yandexgpt",
        "completionOptions": {
            "temperature": 0.6, 
            "maxTokens": 1000
            },
        "messages": [
            {
                "role": "system",
                "text": system_pormpt
            },
            {
                "role": "user",
                "text": f"{user_query}"
            }
        ]
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            config.YANDEX_GPT_PATH,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {config.YANDEX_GPT_TOKEN}"
            },
            json=data
        ) as resp:
            response_json = await resp.json()
    
    return response_json['result']['alternatives'][0]['message']['text']

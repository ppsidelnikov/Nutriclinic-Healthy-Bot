"""
Текстовый нутрициолог на GPT-4.1 через ProxyAPI.
История диалога хранится в формате {role, content} — передаётся напрямую в OpenAI.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import List, Dict, Tuple

from openai import AsyncOpenAI

sys.path.append(str(Path(__file__).parent.parent))

from config.config import config

# Цены ProxyAPI с НДС, ₽ за 1М токенов
_PRICES: Dict[str, Dict[str, float]] = {
    "gpt-4.1":              {"input": 516.0,  "output": 2062.0},
    "gpt-4.1-mini":         {"input": 104.0,  "output": 413.0},
    "gpt-4.1-nano":         {"input": 26.0,   "output": 104.0},
    "claude-sonnet-4-6":    {"input": 774.0,  "output": 3866.0},
    "claude-haiku-4-5":     {"input": 295.0,  "output": 1474.0},
    "gpt-4o":               {"input": 645.0,  "output": 2577.0},
    "gpt-4o-mini":          {"input": 39.0,   "output": 155.0},
}


def strip_markdown(text: str) -> str:
    """Убирает markdown-артефакты которые не рендерятся в Telegram plain text."""
    # Заголовки ### ## # → просто текст
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    # **жирный** и __жирный__ → просто текст
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    # *курсив* и _курсив_ → просто текст
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"_(.+?)_", r"\1", text)
    # Убираем лишние пустые строки (больше двух подряд)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def calc_price(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Возвращает стоимость запроса в рублях или None если модель неизвестна."""
    prices = _PRICES.get(model)
    if not prices:
        return None
    return (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000

SYSTEM_PROMPT = """\
Ты — опытный врач-нутрициолог с медицинским образованием и 15-летним опытом работы. \
Твоя задача — давать профессиональные консультации по вопросам питания, метаболизма и здоровья, основываясь на научных данных и клиническом опыте. \
Основная твоя задача — вести пациентов по похудению, поэтому старайся давать максимально точные советы про это.

Придерживайся следующих принципов:

1. Всегда опирайся на научно подтверждённые факты и современные исследования в области нутрициологии и диетологии.
2. Используй медицинскую терминологию, но объясняй сложные понятия простым языком.
3. Давай персонализированные рекомендации, учитывая индивидуальные особенности человека.
4. Обращай внимание на противопоказания и возможные риски при рекомендации диет и добавок.
5. При необходимости рекомендуй обратиться к специалистам для очной консультации.
6. Приводи примеры продуктов, рационов питания и практических рекомендаций.
7. Не давай категоричных диагнозов и не назначай лечение заболеваний.
8. Учитывай культурные и региональные особенности питания.

Формат ответов:
- Отвечай коротко и по делу — максимум 3-5 коротких абзаца или список до 5 пунктов.
- Не повторяй вопрос пользователя, не делай длинных вступлений.
- Если нужно дать развёрнутый ответ — предложи уточнить отдельно.
- ВАЖНО: не используй markdown-разметку — никаких #, ##, ###, **, __, *, _. \
Только обычный текст. Для списков используй дефис (-).

Профиль пользователя:
- Если в разделе "Информация о пользователе" нет данных — в конце своего ответа добавь одну короткую фразу: \
"Кстати, если заполните профиль (/profile), смогу давать точные персональные рекомендации."\
"""


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=config.PROXY_API_TEST_KEY,
        base_url=config.PROXY_API_BASE_URL,
    )


def _to_openai_messages(
    history: List[Dict[str, str]] | None,
    user_query: str,
    system_text: str,
) -> List[Dict[str, str]]:
    """
    Собирает список сообщений для OpenAI API.
    История хранится в формате {role, content} — передаём напрямую.
    """
    messages = [{"role": "system", "content": system_text}]

    if history:
        messages.extend(history)

    messages.append({"role": "user", "content": user_query})
    return messages


MODEL = "gpt-4.1-mini"


async def get_answer_from_gpt_text(
    user_query: str,
    history: List[Dict[str, str]] | None = None,
    user_context: str = "",
    rag_context: str = "",
    profile_filled: bool = True,
) -> Tuple[str, Dict]:
    """
    Отправляет запрос к GPT-4.1 с историей диалога, профилем и RAG-чанками.

    :param user_query:   Текущее сообщение пользователя.
    :param history:      История [{role, content}, ...] из Redis/Postgres.
    :param user_context: Профиль пользователя (из format_profile_context).
    :param rag_context:  Релевантные чанки базы знаний (из format_rag_context).

    :returns: (ответ_модели, usage_dict)
              usage_dict: {model, input_tokens, output_tokens, price_rub}
    """
    system_text = SYSTEM_PROMPT
    if user_context:
        system_text += f"\n\n{user_context}"
    else:
        system_text += "\n\nИнформация о пользователе: не заполнена."
    if rag_context:
        system_text += f"\n\n{rag_context}"

    messages = _to_openai_messages(history, user_query, system_text)

    response = await _client().chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=0.6,
        max_tokens=1500,
    )

    text          = strip_markdown(response.choices[0].message.content)
    input_tokens  = response.usage.prompt_tokens
    output_tokens = response.usage.completion_tokens

    usage = {
        "model":         MODEL,
        "input_tokens":  input_tokens,
        "output_tokens": output_tokens,
        "price_rub":     calc_price(MODEL, input_tokens, output_tokens),
    }

    return text, usage

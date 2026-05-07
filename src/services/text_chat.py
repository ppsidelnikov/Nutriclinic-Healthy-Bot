"""
Текстовый нутрициолог-консультант на gpt-4.1-mini через ProxyAPI.

Объединяет три источника контекста (см. §2.2 / §2.4 диссертации):
  - profile (профиль пользователя)
  - rag_context (R6-поиск по корпусу нутрициологических знаний)
  - diary_context (текущий дневник на сегодня) + tool calling для исторических данных

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
Только обычный текст. Для списков используй дефис (-)."""

# Инструкция, которая добавляется ТОЛЬКО если профиль не заполнен.
PROFILE_HINT_INSTRUCTION = (
    '\n\nЕсли уместно, в конце ответа можешь добавить ОДНУ короткую фразу: '
    '"Кстати, если заполните профиль (/profile), смогу давать точные персональные рекомендации." '
    'Не добавляй её повторно, если уже была в недавних сообщениях истории.'
)


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
    diary_context: str = "",
    capabilities_context: str = "",
    profile_filled: bool = True,
    telegram_id: str | None = None,
    enable_tools: bool = True,
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
    # Текущее время МСК — чтобы модель отличала настоящее «сегодня» от
    # вчерашних реплик бота в истории чата (там тоже встречалось слово «сегодня»).
    from datetime import datetime, timezone, timedelta
    _msk = datetime.now(timezone(timedelta(hours=3)))
    _date_block = (
        f"Текущая дата и время: {_msk.strftime('%d.%m.%Y, %H:%M')} (МСК).\n"
        f"Слово «сегодня» в любых сообщениях истории относилось к ТОМУ дню, "
        f"а не к нынешнему. Опирайся на текущую дату и блок «Дневник питания на сегодня» ниже, "
        f"а не на упоминания «сегодня» в истории чата."
    )

    system_text = SYSTEM_PROMPT + "\n\n" + _date_block
    if user_context:
        # Профиль заполнен — даём LLM фактические данные и НЕ просим
        # добавлять предложение заполнить профиль.
        system_text += f"\n\n{user_context}"
    else:
        # Профиль пустой — добавляем инструкцию-подсказку.
        system_text += "\n\nИнформация о пользователе: не заполнена."
        system_text += PROFILE_HINT_INSTRUCTION
    if rag_context:
        system_text += f"\n\n{rag_context}"
    if diary_context:
        # Вариант B (§дневник питания) — прокидываем съеденное и цели в контекст
        # LLM, чтобы бот мог естественно учитывать прогресс при ответе.
        system_text += f"\n\n{diary_context}"
        system_text += (
            "\nЕсли вопрос пользователя касается рациона, оценки приёма пищи "
            "или планирования — учитывай эти данные. Не пересказывай таблицу "
            "целиком, упоминай только цифры, релевантные вопросу."
        )
    if capabilities_context:
        # Возможности бота — чтобы LLM могла сама объяснить функционал
        # на свободные вопросы вида «что ты умеешь?», «как добавить в дневник?» и т. д.
        system_text += f"\n\n{capabilities_context}"

    messages = _to_openai_messages(history, user_query, system_text)

    # Tool-calling loop: LLM может запросить выполнение функций
    # для получения исторических данных пользователя (вес, дневник).
    tools_param = None
    if enable_tools and telegram_id:
        from services.tools import get_tool_schemas, execute_tool
        tools_param = get_tool_schemas()

    total_input = total_output = 0
    tool_calls_log: list[dict] = []
    side_effects: list[dict] = []   # инструкции для бота: показать клавиатуру и т.п.
    MAX_TOOL_ITERATIONS = 4   # защита от бесконечного цикла

    for iteration in range(MAX_TOOL_ITERATIONS + 1):
        kwargs: Dict = {
            "model":       MODEL,
            "messages":    messages,
            "temperature": 0.6,
            "max_tokens":  1500,
        }
        if tools_param:
            kwargs["tools"] = tools_param

        response = await _client().chat.completions.create(**kwargs)
        msg = response.choices[0].message
        total_input  += response.usage.prompt_tokens
        total_output += response.usage.completion_tokens

        if not msg.tool_calls:
            text = strip_markdown(msg.content or "")
            break

        # LLM попросила вызвать tools. Выполняем все, отдаём результаты обратно.
        messages.append({
            "role":       "assistant",
            "content":    msg.content,
            "tool_calls": [
                {"id": tc.id, "type": tc.type,
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ],
        })

        for tc in msg.tool_calls:
            import json as _json
            args = {}
            try:
                args = _json.loads(tc.function.arguments or "{}")
            except Exception:
                pass
            result = await execute_tool(tc.function.name, args, telegram_id)
            tool_calls_log.append({
                "iteration": iteration,
                "name":      tc.function.name,
                "args":      args,
                "result_summary": list(result.keys()) if isinstance(result, dict) else None,
            })
            # Извлекаем side-effects (инструкции для бот-слоя), не отдаём их LLM
            result_for_llm = result
            if isinstance(result, dict) and "_side_effect" in result:
                side_effects.append(result["_side_effect"])
                result_for_llm = {k: v for k, v in result.items() if k != "_side_effect"}
            messages.append({
                "role":         "tool",
                "tool_call_id": tc.id,
                "content":      _json.dumps(result_for_llm, ensure_ascii=False, default=str),
            })
    else:
        # if loop не вышел через break — отдаём fallback
        text = "Не удалось завершить ответ за допустимое число шагов."

    usage = {
        "model":         MODEL,
        "input_tokens":  total_input,
        "output_tokens": total_output,
        "price_rub":     calc_price(MODEL, total_input, total_output),
        "tool_calls":    tool_calls_log,
        "side_effects":  side_effects,
    }

    return text, usage

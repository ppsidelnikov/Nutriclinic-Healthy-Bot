"""
Function-calling tools для LLM — доступ к персональным данным пользователя.

Каждый tool:
  - имеет JSON-схему (передаётся в OpenAI tools=...);
  - реализован асинхронной функцией; принимает telegram_id и параметры от LLM;
  - возвращает dict (сериализуется в JSON и отдаётся обратно в LLM).

Расширение: добавь новую запись в TOOLS — схема + handler. Остальное автоматически.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from typing import Any, Callable, Awaitable

from sqlalchemy import select, desc, and_, or_, func as sa_func

from db.db import AsyncSessionLocal
from db.models import WeightLog, FoodDiary
from services.food_diary import MOSCOW_TZ, MEAL_LABELS, MEAL_ORDER, add_entry, get_daily_progress
from services.user_profile import get_user_profile
from services.food_parser import parse_food_text

logger = logging.getLogger(__name__)


def _default_meal_type_by_time() -> str:
    """Авто-определение приёма пищи по текущему времени MSK."""
    hour = datetime.now(MOSCOW_TZ).hour
    if 5 <= hour < 11:
        return "breakfast"
    if 11 <= hour < 16:
        return "lunch"
    if 16 <= hour < 22:
        return "dinner"
    return "snack"


# ──────────────────────────────────────────────────────────────────────────────
# Утилиты времени
# ──────────────────────────────────────────────────────────────────────────────
def _msk_day_range(days_ago: int) -> tuple[datetime, datetime]:
    """Возвращает [start, end) UTC для дня MSK с указанным смещением."""
    now_msk = datetime.now(MOSCOW_TZ)
    target_day = (now_msk - timedelta(days=days_ago)).date()
    start_msk = datetime.combine(target_day, time.min, tzinfo=MOSCOW_TZ)
    end_msk = start_msk + timedelta(days=1)
    return (
        start_msk.astimezone(timezone.utc).replace(tzinfo=None),
        end_msk.astimezone(timezone.utc).replace(tzinfo=None),
    )


def _date_to_msk_range(date_str: str) -> tuple[datetime, datetime]:
    """date в формате YYYY-MM-DD → [start, end) UTC."""
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    start_msk = datetime.combine(d, time.min, tzinfo=MOSCOW_TZ)
    end_msk = start_msk + timedelta(days=1)
    return (
        start_msk.astimezone(timezone.utc).replace(tzinfo=None),
        end_msk.astimezone(timezone.utc).replace(tzinfo=None),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Tool 1: get_weight_history
# ──────────────────────────────────────────────────────────────────────────────
async def _tool_get_weight_history(telegram_id: str, *, days_back: int = 30, limit: int = 10) -> dict:
    cutoff = datetime.utcnow() - timedelta(days=int(days_back))
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(WeightLog)
            .where(WeightLog.telegram_id == telegram_id)
            .where(WeightLog.recorded_at >= cutoff)
            .order_by(desc(WeightLog.recorded_at))
            .limit(int(limit))
        )).scalars().all()

    if not rows:
        return {"entries": [], "summary": "Записей веса за указанный период нет."}

    entries = [
        {
            "date":      r.recorded_at.replace(tzinfo=timezone.utc)
                           .astimezone(MOSCOW_TZ).strftime("%Y-%m-%d %H:%M"),
            "weight_kg": round(r.weight_kg, 1),
        }
        for r in rows
    ]
    return {
        "entries": entries,
        "current_weight_kg": entries[0]["weight_kg"],
        "earliest_in_window": entries[-1],
        "delta_kg": round(entries[0]["weight_kg"] - entries[-1]["weight_kg"], 1),
        "n": len(entries),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Tool 2: get_diary_for_date
# ──────────────────────────────────────────────────────────────────────────────
async def _tool_get_diary_for_date(telegram_id: str, *, days_ago: int = None, date: str = None) -> dict:
    if days_ago is not None:
        start, end = _msk_day_range(int(days_ago))
        label_date = (datetime.now(MOSCOW_TZ) - timedelta(days=int(days_ago))).strftime("%Y-%m-%d")
    elif date:
        start, end = _date_to_msk_range(date)
        label_date = date
    else:
        return {"error": "укажи days_ago или date"}

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(FoodDiary)
            .where(FoodDiary.telegram_id == telegram_id)
            .where(FoodDiary.eaten_at >= start)
            .where(FoodDiary.eaten_at < end)
            .order_by(FoodDiary.eaten_at)
        )).scalars().all()

    if not rows:
        return {"date": label_date, "entries": [], "totals": None,
                "summary": f"За {label_date} записей в дневнике нет."}

    by_meal: dict[str, list[dict]] = {m: [] for m in MEAL_ORDER}
    totals = {"kcal": 0.0, "protein": 0.0, "fat": 0.0, "carbs": 0.0}
    for r in rows:
        by_meal.setdefault(r.meal_type, []).append({
            "dish_name": r.dish_name,
            "portion_g": r.portion_g,
            "kcal":      round(r.kcal, 0),
            "protein_g": round(r.protein_g or 0, 1),
            "fat_g":     round(r.fat_g or 0, 1),
            "carbs_g":   round(r.carbs_g or 0, 1),
        })
        totals["kcal"]    += r.kcal or 0
        totals["protein"] += r.protein_g or 0
        totals["fat"]     += r.fat_g or 0
        totals["carbs"]   += r.carbs_g or 0
    totals = {k: round(v, 1) for k, v in totals.items()}
    return {"date": label_date, "by_meal": by_meal, "totals": totals, "n_entries": len(rows)}


# ──────────────────────────────────────────────────────────────────────────────
# Tool 3: get_diary_summary
# ──────────────────────────────────────────────────────────────────────────────
async def _tool_get_diary_summary(telegram_id: str, *, days_back: int = 7) -> dict:
    days_back = int(days_back)
    end_msk = datetime.now(MOSCOW_TZ)
    start_msk = datetime.combine((end_msk - timedelta(days=days_back)).date(), time.min, tzinfo=MOSCOW_TZ)
    start = start_msk.astimezone(timezone.utc).replace(tzinfo=None)
    end = end_msk.astimezone(timezone.utc).replace(tzinfo=None)

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(FoodDiary)
            .where(FoodDiary.telegram_id == telegram_id)
            .where(FoodDiary.eaten_at >= start)
            .where(FoodDiary.eaten_at < end)
        )).scalars().all()

    if not rows:
        return {"days_back": days_back, "n_entries": 0,
                "summary": f"За {days_back} дней записей нет."}

    # группировка по дням MSK
    by_day: dict[str, dict] = {}
    for r in rows:
        d = r.eaten_at.replace(tzinfo=timezone.utc).astimezone(MOSCOW_TZ).date().isoformat()
        agg = by_day.setdefault(d, {"kcal": 0, "protein": 0, "fat": 0, "carbs": 0, "n": 0})
        agg["kcal"]    += r.kcal or 0
        agg["protein"] += r.protein_g or 0
        agg["fat"]     += r.fat_g or 0
        agg["carbs"]   += r.carbs_g or 0
        agg["n"]       += 1

    days_with_entries = len(by_day)
    avg = {k: round(sum(d[k] for d in by_day.values()) / days_with_entries, 1)
           for k in ["kcal", "protein", "fat", "carbs"]}
    return {
        "days_back":         days_back,
        "n_entries":         len(rows),
        "days_with_entries": days_with_entries,
        "avg_per_day":       avg,
        "by_day":            {d: {"kcal": round(v["kcal"], 0), "n": v["n"]} for d, v in sorted(by_day.items())},
    }


# ──────────────────────────────────────────────────────────────────────────────
# Tool 4: search_diary
# ──────────────────────────────────────────────────────────────────────────────
async def _tool_search_diary(telegram_id: str, *, query: str, days_back: int = 30) -> dict:
    cutoff = datetime.utcnow() - timedelta(days=int(days_back))
    pattern = f"%{query.lower().strip()}%"
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(FoodDiary)
            .where(FoodDiary.telegram_id == telegram_id)
            .where(FoodDiary.eaten_at >= cutoff)
            .where(sa_func.lower(FoodDiary.dish_name).like(pattern))
            .order_by(desc(FoodDiary.eaten_at))
            .limit(20)
        )).scalars().all()

    if not rows:
        return {"query": query, "matches": [],
                "summary": f"За {days_back} дней '{query}' в дневнике нет."}

    matches = [
        {
            "date":        r.eaten_at.replace(tzinfo=timezone.utc)
                             .astimezone(MOSCOW_TZ).strftime("%Y-%m-%d %H:%M"),
            "dish_name":   r.dish_name,
            "meal_type":   r.meal_type,
            "kcal":        round(r.kcal, 0),
            "portion_g":   r.portion_g,
        }
        for r in rows
    ]
    total_kcal = sum(m["kcal"] for m in matches)
    return {
        "query":      query,
        "n_matches":  len(matches),
        "total_kcal": round(total_kcal, 0),
        "last":       matches[0],
        "matches":    matches[:10],   # урезаем для контекста LLM
    }


# ──────────────────────────────────────────────────────────────────────────────
# Tool 5: quick_add_food (write — добавляет запись в дневник напрямую)
# ──────────────────────────────────────────────────────────────────────────────
async def _tool_quick_add_food(telegram_id: str, *, text: str, meal_type: str = None) -> dict:
    """Парсит описание блюда. ЗАПИСЬ НЕ ДЕЛАЕТСЯ напрямую — мы только готовим
    pending-запись и просим бот показать пользователю кнопки выбора приёма пищи.

    Это сохраняет UX, идентичный команде /add (распознал X, куда записать?),
    при этом LLM может реагировать на свободные фразы вроде «я съел яблоко».
    """
    if not text or not text.strip():
        return {"error": "пустое описание"}

    parsed = await parse_food_text(text)
    if not parsed:
        return {"error": "не удалось разобрать описание блюда"}

    # Готовим pending-запись и регистрируем её в общем in-memory кэше handler-слоя
    import uuid
    from handlers.food_diary_handlers import remember_entry  # lazy: избегаем цикла

    temp_id = f"tool_{uuid.uuid4().hex[:12]}"
    payload = {
        "dish_name": parsed["dish_name"],
        "portion_g": parsed.get("portion_g"),
        "kcal":      parsed["kcal"],
        "protein_g": parsed.get("protein_g"),
        "fat_g":     parsed.get("fat_g"),
        "carbs_g":   parsed.get("carbs_g"),
        "source":    "llm_quick_add",
    }
    remember_entry(temp_id, payload)

    # LLM не должна сама писать «✓ записал...» — это сделает бот после показа
    # клавиатуры и нажатия пользователя. Просим её просто закрыть свою реплику
    # коротким сообщением, поскольку UI пойдёт следом.
    return {
        "parsed_dish":  parsed["dish_name"],
        "portion_g":    parsed.get("portion_g"),
        "kcal":         round(parsed["kcal"], 0),
        "protein_g":    round(parsed.get("protein_g", 0), 1),
        "fat_g":        round(parsed.get("fat_g", 0), 1),
        "carbs_g":      round(parsed.get("carbs_g", 0), 1),
        "next_step":    "Бот сейчас покажет кнопки выбора приёма пищи. "
                        "Не пиши «записал» в ответе — запись произойдёт после клика пользователя. "
                        "Можешь добавить очень короткое подтверждение «понял» или вообще не отвечать.",
        "_side_effect": {
            "type":      "show_meal_keyboard",
            "temp_id":   temp_id,
            "dish_name": parsed["dish_name"],
            "kcal":      round(parsed["kcal"], 0),
            "portion_g": parsed.get("portion_g"),
            "protein_g": round(parsed.get("protein_g", 0), 1),
            "fat_g":     round(parsed.get("fat_g", 0), 1),
            "carbs_g":   round(parsed.get("carbs_g", 0), 1),
            "meal_type_hint": meal_type if meal_type in MEAL_LABELS else None,
        },
    }


# ──────────────────────────────────────────────────────────────────────────────
# Регистр tools — схемы для OpenAI и обработчики
# ──────────────────────────────────────────────────────────────────────────────
TOOLS: dict[str, dict] = {
    "get_weight_history": {
        "schema": {
            "type": "function",
            "function": {
                "name": "get_weight_history",
                "description": (
                    "Получить записи веса пользователя за последние N дней. "
                    "Используй когда пользователь спрашивает о весе в прошлом, "
                    "о динамике, тренде, или хочет сравнить с прошлым."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "days_back": {"type": "integer", "description": "За сколько дней назад искать"},
                        "limit":     {"type": "integer", "description": "Максимум записей в ответе"},
                    },
                },
            },
        },
        "handler": _tool_get_weight_history,
    },
    "get_diary_for_date": {
        "schema": {
            "type": "function",
            "function": {
                "name": "get_diary_for_date",
                "description": (
                    "Получить записи дневника питания за конкретный день. "
                    "Используй когда пользователь спрашивает что он ел вчера, "
                    "позавчера или в конкретную дату."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "days_ago": {"type": "integer",
                                     "description": "0 — сегодня, 1 — вчера, 2 — позавчера и т.д."},
                        "date":     {"type": "string",
                                     "description": "Альтернативно: дата в формате YYYY-MM-DD"},
                    },
                },
            },
        },
        "handler": _tool_get_diary_for_date,
    },
    "get_diary_summary": {
        "schema": {
            "type": "function",
            "function": {
                "name": "get_diary_summary",
                "description": (
                    "Сводка по дневнику за период: средние калории и БЖУ за день, "
                    "разбивка по дням, общее число записей. Используй для вопросов "
                    "о среднем потреблении, дефиците, тренде питания за неделю/месяц."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "days_back": {"type": "integer",
                                      "description": "За сколько дней назад агрегировать (например 7 или 30)"},
                    },
                    "required": ["days_back"],
                },
            },
        },
        "handler": _tool_get_diary_summary,
    },
    "search_diary": {
        "schema": {
            "type": "function",
            "function": {
                "name": "search_diary",
                "description": (
                    "Найти записи в дневнике по названию блюда или ингредиента. "
                    "Используй для вопросов «когда последний раз ел Х», "
                    "«сколько раз ел Х за период», «сколько было Х»."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query":     {"type": "string",
                                      "description": "Название еды для поиска (русский или английский)"},
                        "days_back": {"type": "integer",
                                      "description": "За сколько дней искать (по умолчанию 30)"},
                    },
                    "required": ["query"],
                },
            },
        },
        "handler": _tool_search_diary,
    },
    "quick_add_food": {
        "schema": {
            "type": "function",
            "function": {
                "name": "quick_add_food",
                "description": (
                    "Добавить запись в дневник питания пользователя по короткому описанию. "
                    "Используй когда пользователь явно сообщает что съел/выпил что-то "
                    "(«съел яблоко», «обедал курицей с рисом», «выпил кофе с молоком», "
                    "«запиши овсянку 250г на завтрак»). НЕ используй на вопросах "
                    "(«что мне поесть?», «сколько калорий в Х?») — они не требуют записи. "
                    "Если приём пищи не указан явно, можно опустить — определится по времени суток."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "Описание блюда от пользователя, как есть (например 'яблоко' или 'овсянка с ягодами 300г')",
                        },
                        "meal_type": {
                            "type": "string",
                            "enum": ["breakfast", "lunch", "dinner", "snack"],
                            "description": "Приём пищи, если пользователь явно его указал (завтрак/обед/ужин/перекус)",
                        },
                    },
                    "required": ["text"],
                },
            },
        },
        "handler": _tool_quick_add_food,
    },
}


def get_tool_schemas() -> list[dict]:
    """Возвращает список схем для передачи в OpenAI tools=."""
    return [t["schema"] for t in TOOLS.values()]


async def execute_tool(name: str, args: dict, telegram_id: str) -> dict:
    """Выполнить tool. Возвращает результат для последующей передачи в LLM."""
    if name not in TOOLS:
        return {"error": f"unknown tool: {name}"}
    handler: Callable[..., Awaitable[dict]] = TOOLS[name]["handler"]
    try:
        return await handler(telegram_id, **(args or {}))
    except Exception as e:
        logger.exception("tool %s failed: %s", name, e)
        return {"error": f"{type(e).__name__}: {e}"}

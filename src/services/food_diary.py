"""
Дневник питания: добавление/удаление записей, сводка за день.

Все timestamps хранятся в UTC. Понятие «сегодня» вычисляется в часовом поясе
Москвы (UTC+3) — для MVP захардкожено; в будущем можно сделать настройку
часового пояса в user_profile.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Optional

from sqlalchemy import select, delete, func, text

from db.db import AsyncSessionLocal
from db.models import FoodDiary

MOSCOW_TZ = timezone(timedelta(hours=3))

MEAL_LABELS = {
    "breakfast": "🍳 Завтрак",
    "lunch":     "🥗 Обед",
    "dinner":    "🍽 Ужин",
    "snack":     "☕ Перекус",
}
MEAL_ORDER = ["breakfast", "lunch", "dinner", "snack"]

# Стандартное распределение макронутриентов по доле калорий: 25 % белка,
# 30 % жира, 45 % углеводов. Соотношение приближено к рекомендациям ВОЗ
# и DGA для сбалансированного рациона.
MACRO_RATIO = {"protein": 0.25, "fat": 0.30, "carbs": 0.45}
KCAL_PER_GRAM = {"protein": 4, "fat": 9, "carbs": 4}


def compute_targets(daily_kcal_target: float | None) -> dict | None:
    """Из целевых ккал вычисляет таргеты по БЖУ. None если цели нет."""
    if not daily_kcal_target or daily_kcal_target <= 0:
        return None
    return {
        "kcal":    float(daily_kcal_target),
        "protein": daily_kcal_target * MACRO_RATIO["protein"] / KCAL_PER_GRAM["protein"],
        "fat":     daily_kcal_target * MACRO_RATIO["fat"]     / KCAL_PER_GRAM["fat"],
        "carbs":   daily_kcal_target * MACRO_RATIO["carbs"]   / KCAL_PER_GRAM["carbs"],
    }


async def get_streak(telegram_id: str) -> int:
    """Сколько дней подряд (заканчивая сегодня или вчера) есть хотя бы 1 запись.

    Отсутствие записей сегодня не сбрасывает streak — даём 1 «грейс-день»
    (например ещё не успел поесть утром); проверяем только до вчера.
    """
    sql = text("""
        SELECT DISTINCT DATE((eaten_at AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Moscow')::timestamp) AS d
        FROM food_diary
        WHERE telegram_id = :tg
        ORDER BY d DESC
        LIMIT 60
    """)
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(sql, {"tg": str(telegram_id)})).fetchall()
    if not rows:
        return 0

    today_msk = datetime.now(MOSCOW_TZ).date()
    days_with_entries = [r[0] for r in rows]   # отсортированы по убыванию

    streak = 0
    expected = today_msk
    # допустим грейс-день: если сегодня нет записей, начинаем с вчера
    if days_with_entries[0] != today_msk:
        expected = today_msk - timedelta(days=1)

    for d in days_with_entries:
        if d == expected:
            streak += 1
            expected -= timedelta(days=1)
        elif d < expected:
            break
    return streak


async def get_week_summary(telegram_id: str, days_back: int = 7) -> dict:
    """Среднее за день и тренд за последние N дней."""
    end = datetime.now(MOSCOW_TZ)
    start_msk = datetime.combine((end - timedelta(days=days_back)).date(), time.min, tzinfo=MOSCOW_TZ)
    start_utc = start_msk.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc   = end.astimezone(timezone.utc).replace(tzinfo=None)

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(FoodDiary)
            .where(FoodDiary.telegram_id == str(telegram_id))
            .where(FoodDiary.eaten_at >= start_utc)
            .where(FoodDiary.eaten_at < end_utc)
        )).scalars().all()

    if not rows:
        return {"days_back": days_back, "n_entries": 0, "by_day": {}}

    by_day: dict = {}
    for r in rows:
        d = r.eaten_at.replace(tzinfo=timezone.utc).astimezone(MOSCOW_TZ).date()
        agg = by_day.setdefault(d, {"kcal": 0.0, "protein": 0.0, "fat": 0.0, "carbs": 0.0, "n": 0})
        agg["kcal"]    += r.kcal or 0
        agg["protein"] += r.protein_g or 0
        agg["fat"]     += r.fat_g or 0
        agg["carbs"]   += r.carbs_g or 0
        agg["n"]       += 1

    days_with = len(by_day)
    avg = {k: sum(d[k] for d in by_day.values()) / days_with
           for k in ("kcal", "protein", "fat", "carbs")}
    return {
        "days_back":         days_back,
        "n_entries":         len(rows),
        "days_with_entries": days_with,
        "avg":               {k: round(v, 1) for k, v in avg.items()},
        "by_day":            by_day,
    }


async def get_top_dishes(telegram_id: str, days_back: int = 14, limit: int = 8) -> list[dict]:
    """Топ N самых частых блюд за последние N дней — авто-шаблоны.

    Возвращает [{"dish_name", "count", "avg_kcal", "avg_protein", "avg_fat",
                 "avg_carbs", "avg_portion_g", "last_meal_type"}, ...]
    """
    sql = text("""
        WITH ranked AS (
            SELECT
                dish_name,
                kcal, protein_g, fat_g, carbs_g, portion_g, meal_type,
                eaten_at,
                ROW_NUMBER() OVER (PARTITION BY dish_name ORDER BY eaten_at DESC) AS rn
            FROM food_diary
            WHERE telegram_id = :tg
              AND eaten_at >= now() - make_interval(days => :days)
        )
        SELECT
            dish_name,
            COUNT(*)              AS cnt,
            AVG(kcal)             AS avg_kcal,
            AVG(protein_g)        AS avg_p,
            AVG(fat_g)            AS avg_f,
            AVG(carbs_g)          AS avg_c,
            AVG(portion_g)        AS avg_portion,
            MAX(CASE WHEN rn = 1 THEN meal_type END) AS last_meal_type,
            MAX(eaten_at)         AS last_eaten
        FROM ranked
        GROUP BY dish_name
        ORDER BY cnt DESC, last_eaten DESC
        LIMIT :n
    """)
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(sql, {"tg": str(telegram_id), "days": days_back, "n": limit})).fetchall()
    return [
        {
            "dish_name":      r[0],
            "count":          int(r[1]),
            "avg_kcal":       round(float(r[2] or 0), 0),
            "avg_protein":    round(float(r[3] or 0), 1),
            "avg_fat":        round(float(r[4] or 0), 1),
            "avg_carbs":      round(float(r[5] or 0), 1),
            "avg_portion_g":  float(r[6]) if r[6] else None,
            "last_meal_type": r[7],
        }
        for r in rows
    ]


async def get_entry_by_id(telegram_id: str, entry_id: int) -> Optional[dict]:
    """Получить одну запись по id (с проверкой telegram_id)."""
    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            select(FoodDiary)
            .where(FoodDiary.id == entry_id)
            .where(FoodDiary.telegram_id == str(telegram_id))
        )).scalars().first()
    if not row:
        return None
    return {
        "id":         row.id,
        "dish_name":  row.dish_name,
        "portion_g":  row.portion_g,
        "kcal":       row.kcal,
        "protein_g":  row.protein_g,
        "fat_g":      row.fat_g,
        "carbs_g":    row.carbs_g,
        "meal_type":  row.meal_type,
    }


async def delete_last_entry(telegram_id: str) -> dict | None:
    """Удаляет самую свежую запись пользователя. Возвращает удалённую запись или None."""
    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            select(FoodDiary)
            .where(FoodDiary.telegram_id == str(telegram_id))
            .order_by(FoodDiary.eaten_at.desc())
            .limit(1)
        )).scalars().first()
        if not row:
            return None
        info = {
            "dish_name": row.dish_name,
            "kcal":      row.kcal,
            "meal_type": row.meal_type,
        }
        await session.delete(row)
        await session.commit()
    return info


async def get_daily_progress(telegram_id: str, daily_kcal_target: float | None,
                             days_ago: int = 0) -> dict:
    """Прогресс за день: что съедено, что осталось до цели по ккал/Б/Ж/У.

    Возвращает:
      {
        "eaten":     {"kcal": X, "protein": ..., "fat": ..., "carbs": ...},
        "target":    {"kcal": ..., "protein": ..., ...} | None,
        "remaining": {"kcal": ..., "protein": ..., ...} | None,
        "pct":       {"kcal": ..., ...} | None,
        "by_meal":   {breakfast: [...], lunch: [...], ...},
      }
    """
    snapshot = await get_today(telegram_id, days_ago=days_ago)
    eaten = snapshot["totals"]
    target = compute_targets(daily_kcal_target)

    out: dict = {
        "eaten":   eaten,
        "target":  target,
        "by_meal": snapshot["by_meal"],
    }
    if target:
        out["remaining"] = {k: target[k] - eaten[k] for k in target}
        out["pct"] = {
            k: (eaten[k] / target[k] * 100) if target[k] > 0 else 0.0
            for k in target
        }
    else:
        out["remaining"] = None
        out["pct"] = None
    return out


def _kcal_status_emoji(pct: float) -> str:
    """Эмодзи-индикатор по проценту от цели."""
    if pct < 60:    return "🔵"   # ещё далеко до цели
    if pct < 90:    return "🟢"   # норма
    if pct < 105:   return "🟡"   # близко к цели — внимание
    if pct < 120:   return "🟠"   # перебор
    return "🔴"                    # значительный перебор


def format_progress_line(progress: dict) -> str:
    """Краткая строка прогресса для подтверждений «после /add» — в plain text."""
    eaten = progress["eaten"]
    target = progress.get("target")
    if not target:
        return f"Сегодня: {eaten['kcal']:.0f} ккал (цель не задана)"
    pct = progress["pct"]["kcal"]
    remaining = progress["remaining"]["kcal"]
    status = _kcal_status_emoji(pct)
    if remaining < 0:
        tail = f"перебор {abs(remaining):.0f} ккал"
    else:
        tail = f"осталось {remaining:.0f}"
    return (
        f"{status} Сегодня: {eaten['kcal']:.0f}/{target['kcal']:.0f} ккал "
        f"({pct:.0f}%, {tail})"
    )


def format_progress_block(progress: dict, streak: int = 0) -> str:
    """Расширенный HTML-блок с КБЖУ для шапки /today."""
    eaten = progress["eaten"]
    target = progress.get("target")

    streak_line = ""
    if streak >= 2:
        streak_line = f"🔥 <b>{streak} дней подряд</b> с записями\n"

    if not target:
        return (
            f"{streak_line}"
            f"<b>Всего:</b> {eaten['kcal']:.0f} ккал  "
            f"(Б {eaten['protein']:.0f} / Ж {eaten['fat']:.0f} / У {eaten['carbs']:.0f})\n"
            "<i>Цель не задана — заполни /profile или используй /set_calories.</i>"
        )
    pct = progress["pct"]
    rem = progress["remaining"]
    status = _kcal_status_emoji(pct["kcal"])
    rem_text = f"осталось {rem['kcal']:.0f}" if rem["kcal"] >= 0 else f"перебор {abs(rem['kcal']):.0f}"
    return (
        f"{streak_line}"
        f"{status} <b>Калории:</b> {eaten['kcal']:.0f} / {target['kcal']:.0f} ккал "
        f"({pct['kcal']:.0f}%, {rem_text})\n"
        f"<b>Белки:</b> {eaten['protein']:.0f} / {target['protein']:.0f} г "
        f"({pct['protein']:.0f}%)\n"
        f"<b>Жиры:</b> {eaten['fat']:.0f} / {target['fat']:.0f} г "
        f"({pct['fat']:.0f}%)\n"
        f"<b>Углеводы:</b> {eaten['carbs']:.0f} / {target['carbs']:.0f} г "
        f"({pct['carbs']:.0f}%)"
    )


def format_progress_for_llm(progress: dict) -> str:
    """Plain-text блок для системного промпта LLM (вариант B)."""
    eaten = progress["eaten"]
    target = progress.get("target")
    lines = ["Дневник питания пользователя на сегодня:"]
    lines.append(
        f"- Съедено: {eaten['kcal']:.0f} ккал, "
        f"Б {eaten['protein']:.0f} г, Ж {eaten['fat']:.0f} г, У {eaten['carbs']:.0f} г"
    )
    if target:
        rem = progress["remaining"]
        pct = progress["pct"]
        lines.append(
            f"- Цель на день: {target['kcal']:.0f} ккал, "
            f"Б {target['protein']:.0f} г, Ж {target['fat']:.0f} г, У {target['carbs']:.0f} г"
        )
        lines.append(
            f"- Осталось до цели: {rem['kcal']:.0f} ккал ({100 - pct['kcal']:.0f}%), "
            f"Б {rem['protein']:.0f} г, Ж {rem['fat']:.0f} г, У {rem['carbs']:.0f} г"
        )
    else:
        lines.append("- Целевые калории/БЖУ в профиле не заданы.")
    n_entries = sum(len(v) for v in progress["by_meal"].values())
    lines.append(f"- Записей в дневнике сегодня: {n_entries}")
    return "\n".join(lines)


def _msk_day_range(days_ago: int = 0) -> tuple[datetime, datetime]:
    """Границы дня MSK с указанным offset, переведённые в UTC."""
    now_msk = datetime.now(MOSCOW_TZ)
    target = (now_msk - timedelta(days=days_ago)).date()
    start_msk = datetime.combine(target, time.min, tzinfo=MOSCOW_TZ)
    end_msk = start_msk + timedelta(days=1)
    return start_msk.astimezone(timezone.utc).replace(tzinfo=None), \
           end_msk.astimezone(timezone.utc).replace(tzinfo=None)


def _today_utc_range() -> tuple[datetime, datetime]:
    """Границы «сегодня» по московскому времени (deprecated, используй _msk_day_range)."""
    return _msk_day_range(0)


async def add_entry(
    *,
    telegram_id: str,
    meal_type: str,
    dish_name: str,
    kcal: float,
    portion_g: Optional[float] = None,
    protein_g: Optional[float] = None,
    fat_g: Optional[float] = None,
    carbs_g: Optional[float] = None,
    source: str = "photo",
) -> int:
    """Добавляет запись в дневник. Возвращает id новой записи."""
    if meal_type not in MEAL_LABELS:
        raise ValueError(f"Неизвестный приём пищи: {meal_type}")
    entry = FoodDiary(
        telegram_id=str(telegram_id),
        meal_type=meal_type,
        dish_name=dish_name,
        portion_g=portion_g,
        kcal=kcal,
        protein_g=protein_g,
        fat_g=fat_g,
        carbs_g=carbs_g,
        source=source,
    )
    async with AsyncSessionLocal() as session:
        session.add(entry)
        await session.commit()
        await session.refresh(entry)
        return entry.id


async def delete_entry(entry_id: int, telegram_id: str) -> bool:
    """Удаляет запись по id. Проверяет что она принадлежит пользователю."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            delete(FoodDiary)
            .where(FoodDiary.id == entry_id)
            .where(FoodDiary.telegram_id == str(telegram_id))
        )
        await session.commit()
        return result.rowcount > 0


async def get_today(telegram_id: str, days_ago: int = 0) -> dict:
    """Возвращает структуру дневника за день (по умолчанию сегодня):
    {
      "totals": {kcal, protein, fat, carbs},
      "by_meal": {"breakfast": [{id, dish_name, ...}, ...], ...},
    }
    """
    start, end = _msk_day_range(days_ago)
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(FoodDiary)
            .where(FoodDiary.telegram_id == str(telegram_id))
            .where(FoodDiary.eaten_at >= start)
            .where(FoodDiary.eaten_at < end)
            .order_by(FoodDiary.eaten_at)
        )).scalars().all()

    by_meal: dict[str, list[dict]] = {m: [] for m in MEAL_ORDER}
    totals = {"kcal": 0.0, "protein": 0.0, "fat": 0.0, "carbs": 0.0}
    for r in rows:
        by_meal.setdefault(r.meal_type, []).append({
            "id":        r.id,
            "dish_name": r.dish_name,
            "portion_g": r.portion_g,
            "kcal":      r.kcal,
            "protein":   r.protein_g or 0.0,
            "fat":       r.fat_g or 0.0,
            "carbs":     r.carbs_g or 0.0,
        })
        totals["kcal"]    += r.kcal or 0
        totals["protein"] += r.protein_g or 0
        totals["fat"]     += r.fat_g or 0
        totals["carbs"]   += r.carbs_g or 0
    return {"totals": totals, "by_meal": by_meal}


def format_macro_tips(progress: dict) -> str:
    """Короткие детерминированные подсказки по балансу БЖУ — для показа
    после `/add`. Адаптируются к стадии дня: только начал есть / в норме /
    близко к цели / перебор."""
    target = progress.get("target")
    if not target:
        return ""

    pct = progress["pct"]
    rem = progress["remaining"]
    tips = []

    # 1. Сценарий перебора по калориям
    if pct["kcal"] > 110:
        over = -rem["kcal"]
        tips.append(f"⚠️ Перебор {over:.0f} ккал. На завтра можно небольшой дефицит, если хочешь компенсировать.")
    elif pct["kcal"] > 100:
        over = -rem["kcal"]
        tips.append(f"⚠️ Превышение цели на {over:.0f} ккал. Старайся избегать перекусов до конца дня.")
    elif pct["kcal"] >= 85:
        tips.append(f"💡 До цели осталось {rem['kcal']:.0f} ккал — выбирай лёгкое (овощи, белок).")

    # 2. Подсказки по БЖУ — только если целевой день не сильно нарушен
    if pct["kcal"] >= 50:
        if pct["protein"] < pct["kcal"] - 20 and rem["protein"] > 20:
            tips.append(f"💡 Белка ещё на {rem['protein']:.0f} г — добавь рыбу, курицу или творог.")
        if pct["fat"] >= 95 and pct["kcal"] < 100:
            tips.append("💡 Жиров почти норма — на остаток дня лучше постная еда.")
        if pct["carbs"] > 115 and pct["kcal"] < 105:
            tips.append("💡 Углеводов перебор — компенсируй белком и овощами.")

    return "\n".join(tips)


def format_today(progress: dict, streak: int = 0, title: str = "📊 Сегодня") -> str:
    """Сводка за день: прогресс по КБЖУ + разбивка по приёмам пищи."""
    parts = [f"<b>{title}</b>", format_progress_block(progress, streak=streak)]
    any_entries = False
    for meal_type in MEAL_ORDER:
        items = progress["by_meal"].get(meal_type, [])
        if not items:
            continue
        any_entries = True
        meal_kcal = sum(i["kcal"] for i in items)
        parts.append(f"\n<b>{MEAL_LABELS[meal_type]}</b> ({meal_kcal:.0f} ккал)")
        for it in items:
            portion = f", {int(it['portion_g'])} г" if it.get("portion_g") else ""
            parts.append(f"• {it['dish_name']}{portion} — {it['kcal']:.0f} ккал")
    if not any_entries:
        parts.append("\nЗа этот день записей нет.")
    return "\n".join(parts)


def format_week(week: dict, target_kcal: float | None = None) -> str:
    """Сводка за неделю: средние, разбивка по дням, тренд."""
    if week["n_entries"] == 0:
        return (
            "<b>📅 За неделю</b>\n\n"
            "За последние 7 дней записей в дневнике нет.\n"
            "Начни с /add."
        )

    avg = week["avg"]
    parts = [
        "<b>📅 За неделю</b>",
        f"Записей: <b>{week['n_entries']}</b> "
        f"(в {week['days_with_entries']} из 7 дней)",
        "",
        "<b>В среднем за день:</b>",
        f"Калории: <b>{avg['kcal']:.0f} ккал</b>"
        + (f" / цель {target_kcal:.0f}" if target_kcal else ""),
        f"Белки: {avg['protein']:.0f} г, Жиры: {avg['fat']:.0f} г, Углеводы: {avg['carbs']:.0f} г",
        "",
        "<b>По дням:</b>",
    ]
    today_msk = datetime.now(MOSCOW_TZ).date()
    for d in sorted(week["by_day"].keys(), reverse=True):
        agg = week["by_day"][d]
        days_diff = (today_msk - d).days
        if days_diff == 0:
            label = "Сегодня"
        elif days_diff == 1:
            label = "Вчера"
        else:
            label = d.strftime("%d.%m")
        emoji = ""
        if target_kcal:
            pct = agg["kcal"] / target_kcal * 100
            emoji = _kcal_status_emoji(pct) + " "
        parts.append(f"{emoji}{label}: {agg['kcal']:.0f} ккал ({agg['n']} записей)")
    return "\n".join(parts)

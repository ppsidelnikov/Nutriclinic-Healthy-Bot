"""Сервис учёта веса: добавление записей, получение истории и тренда."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, desc

from db.db import AsyncSessionLocal
from db.models import WeightLog
from services.user_profile import upsert_user_profile


async def add_weight(telegram_id: str, weight_kg: float) -> int:
    """Добавляет запись веса и обновляет user_profile.weight_kg на последнее значение."""
    async with AsyncSessionLocal() as session:
        entry = WeightLog(telegram_id=str(telegram_id), weight_kg=weight_kg)
        session.add(entry)
        await session.commit()
        await session.refresh(entry)
        new_id = entry.id
    # синхронизируем с профилем — формула расчёта калорий использует это поле
    await upsert_user_profile(str(telegram_id), weight_kg=weight_kg)
    return new_id


async def get_recent(telegram_id: str, days: int = 30, limit: int = 30) -> list[dict]:
    """Возвращает записи за последние N дней, отсортированные от новых к старым."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(WeightLog)
            .where(WeightLog.telegram_id == str(telegram_id))
            .where(WeightLog.recorded_at >= cutoff)
            .order_by(desc(WeightLog.recorded_at))
            .limit(limit)
        )).scalars().all()
    return [
        {"id": r.id, "weight_kg": r.weight_kg, "recorded_at": r.recorded_at}
        for r in rows
    ]


def compute_trend(entries: list[dict]) -> Optional[dict]:
    """По списку записей за последние 30 дней — последний вес и динамика.

    Возвращает {"current": ..., "delta_30d": ..., "delta_7d": ...} или None если данных мало.
    """
    if not entries:
        return None
    current = entries[0]["weight_kg"]
    now = entries[0]["recorded_at"]

    # ближайшая запись 30 и 7 дней назад
    delta_30d = None
    delta_7d = None
    for e in entries:
        age = (now - e["recorded_at"]).total_seconds() / 86400
        if age >= 7 and delta_7d is None:
            delta_7d = current - e["weight_kg"]
        if age >= 28 and delta_30d is None:
            delta_30d = current - e["weight_kg"]
    return {"current": current, "delta_7d": delta_7d, "delta_30d": delta_30d}


def format_history(entries: list[dict], trend: Optional[dict]) -> str:
    """HTML-сводка для команды /weight без аргументов."""
    if not entries:
        return (
            "<b>📏 Вес не записан</b>\n\n"
            "Чтобы добавить первую запись: <code>/weight 75.4</code>"
        )

    lines = ["<b>📏 История веса</b>"]
    if trend:
        lines.append(f"Текущий: <b>{trend['current']:.1f} кг</b>")
        if trend["delta_7d"] is not None:
            sign = "+" if trend["delta_7d"] >= 0 else ""
            lines.append(f"За неделю: {sign}{trend['delta_7d']:.1f} кг")
        if trend["delta_30d"] is not None:
            sign = "+" if trend["delta_30d"] >= 0 else ""
            lines.append(f"За месяц: {sign}{trend['delta_30d']:.1f} кг")

    lines.append("\n<b>Последние записи:</b>")
    for e in entries[:10]:
        date = e["recorded_at"].strftime("%d.%m %H:%M")
        lines.append(f"• {date} — {e['weight_kg']:.1f} кг")

    if len(entries) > 10:
        lines.append(f"<i>… и ещё {len(entries) - 10} записей за 30 дней</i>")

    lines.append("\nДобавить новую: <code>/weight 75.4</code>")
    return "\n".join(lines)

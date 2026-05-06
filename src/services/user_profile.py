from __future__ import annotations

from sqlalchemy import select
from db.db import AsyncSessionLocal
from db.models import UserProfile


async def get_user_profile(telegram_id: str) -> UserProfile | None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(UserProfile).where(UserProfile.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()


async def upsert_user_profile(telegram_id: str, **kwargs) -> UserProfile:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(UserProfile).where(UserProfile.telegram_id == telegram_id)
        )
        profile = result.scalar_one_or_none()
        if profile:
            for k, v in kwargs.items():
                setattr(profile, k, v)
        else:
            profile = UserProfile(telegram_id=telegram_id, **kwargs)
            session.add(profile)
        await session.commit()
        await session.refresh(profile)
        return profile


def format_profile_context(profile: UserProfile | None) -> str:
    """Форматирует профиль пользователя в текст для системного промпта."""
    if not profile:
        return ""
    lines = ["Информация о пользователе:"]
    if profile.name:
        lines.append(f"- Имя: {profile.name}")
    if profile.age:
        lines.append(f"- Возраст: {profile.age} лет")
    if profile.gender:
        lines.append(f"- Пол: {'мужской' if profile.gender == 'male' else 'женский'}")
    if profile.weight_kg:
        lines.append(f"- Вес: {profile.weight_kg} кг")
    if profile.height_cm:
        lines.append(f"- Рост: {profile.height_cm} см")
    if profile.goal:
        goals = {
            "weight_loss": "снижение веса",
            "muscle_gain": "набор мышечной массы",
            "maintain": "поддержание веса",
        }
        lines.append(f"- Цель: {goals.get(profile.goal, profile.goal)}")
    if profile.daily_calories_target:
        lines.append(f"- Целевые калории: {profile.daily_calories_target} ккал/день")
    if profile.restrictions:
        lines.append(f"- Ограничения / аллергии: {profile.restrictions}")
    return "\n".join(lines) if len(lines) > 1 else ""

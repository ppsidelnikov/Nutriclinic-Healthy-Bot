"""
Двухуровневая память диалога:

  Уровень 1 — Redis (горячая сессия):
    • TTL 4 часа с момента последнего сообщения (скользящее окно).
    • Хранит последние MAX_SESSION_MESSAGES сообщений.

  Уровень 2 — Postgres (долгосрочная память):
    • Все сообщения пишутся в таблицу chat_messages.
    • Если Redis пустой (новая сессия / после паузы) — подгружаем
      последние LOAD_FROM_DB сообщений из Postgres и греем Redis.

  Авто-сжатие:
    • Когда история вырастает до MAX_SESSION_MESSAGES — самые старые
      COMPRESS_CHUNK сообщений сворачиваются в краткий summary через
      YandexGPT и заменяются одним «assistant»-сообщением-суммаризацией.
"""

from __future__ import annotations

import json
from typing import List, Dict

from sqlalchemy import select, insert
from db.db import AsyncSessionLocal
from db.models import ChatMessage
from services.redis_client import get_redis

# ─── Константы ────────────────────────────────────────────────────────────────

SESSION_TTL          = 60 * 60 * 4   # 4 часа — активная сессия в Redis
MAX_SESSION_MESSAGES = 20             # порог, при котором срабатывает авто-сжатие
COMPRESS_CHUNK       = 10            # сколько старых сообщений сжать в summary
LOAD_FROM_DB         = 20            # сколько сообщений грузить из Postgres при промахе Redis


# ─── Ключи Redis ──────────────────────────────────────────────────────────────

def _key(chat_id: int) -> str:
    return f"chat_history:{chat_id}"


# ─── Postgres: чтение / запись ────────────────────────────────────────────────

async def _db_load_recent(chat_id: int, limit: int = LOAD_FROM_DB) -> List[Dict[str, str]]:
    """Загружает последние `limit` сообщений из Postgres."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ChatMessage)
            .where(ChatMessage.chat_id == str(chat_id))
            .order_by(ChatMessage.id.desc())
            .limit(limit)
        )
        rows = result.scalars().all()
    # rows в обратном порядке — разворачиваем
    return [{"role": r.role, "content": r.text} for r in reversed(rows)]


async def _db_save(chat_id: int, role: str, text: str) -> None:
    """Сохраняет одно сообщение в Postgres."""
    async with AsyncSessionLocal() as session:
        session.add(ChatMessage(chat_id=str(chat_id), role=role, text=text))
        await session.commit()


# ─── Redis: чтение / запись ───────────────────────────────────────────────────

async def _redis_get(chat_id: int) -> List[Dict[str, str]] | None:
    """None — ключ отсутствует (промах кэша). [] — список пуст."""
    redis = await get_redis()
    data = await redis.get(_key(chat_id))
    return json.loads(data) if data is not None else None


async def _redis_set(chat_id: int, history: List[Dict[str, str]]) -> None:
    redis = await get_redis()
    await redis.set(
        _key(chat_id),
        json.dumps(history, ensure_ascii=False),
        ex=SESSION_TTL,
    )


# ─── Авто-сжатие ─────────────────────────────────────────────────────────────

async def _maybe_compress(chat_id: int, history: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Если история ≥ MAX_SESSION_MESSAGES — сжимаем первые COMPRESS_CHUNK сообщений
    в краткий summary через YandexGPT и вставляем его вместо них.
    """
    if len(history) < MAX_SESSION_MESSAGES:
        return history

    # Импорт здесь, чтобы избежать циклических зависимостей
    from services.text_chat import get_answer_from_gpt_text

    to_compress = history[:COMPRESS_CHUNK]
    keep = history[COMPRESS_CHUNK:]

    dialogue_text = "\n".join(
        f"{'Пользователь' if m['role'] == 'user' else 'Нутрициолог'}: {m['content']}"
        for m in to_compress
    )
    prompt = (
        "Сделай краткое резюме следующего диалога между пользователем и нутрициологом. "
        "Выдели ключевые факты о пользователе (цели, ограничения, здоровье) "
        "и основные данные консультации. Резюме должно быть компактным — 3-5 предложений.\n\n"
        f"{dialogue_text}"
    )

    try:
        summary = await get_answer_from_gpt_text(prompt)
        summary_msg = {"role": "assistant", "content": f"[Краткое содержание предыдущего диалога]: {summary}"}
        compressed = [summary_msg] + keep
        print(f"[chat_history] Сжато {COMPRESS_CHUNK} → 1 summary для chat_id={chat_id}")
        return compressed
    except Exception as e:
        print(f"[chat_history] Ошибка сжатия: {e}")
        # Если сжатие не удалось — просто обрезаем начало
        return history[-MAX_SESSION_MESSAGES:]


# ─── Публичный API ────────────────────────────────────────────────────────────

async def get_history(chat_id: int) -> List[Dict[str, str]]:
    """
    Возвращает историю диалога для передачи в YandexGPT.
    Redis HIT  → возвращаем из Redis.
    Redis MISS → грузим из Postgres, греем Redis, возвращаем.
    """
    cached = await _redis_get(chat_id)
    if cached is not None:
        return cached

    # Промах — загружаем из Postgres
    db_history = await _db_load_recent(chat_id)
    if db_history:
        await _redis_set(chat_id, db_history)
        print(f"[chat_history] Redis MISS → загружено {len(db_history)} сообщ. из Postgres для chat_id={chat_id}")
    return db_history


async def add_message(chat_id: int, role: str, text: str) -> None:
    """
    Добавляет сообщение в Redis (сессия) и Postgres (долгосрочно).
    При переполнении Redis — авто-сжатие.
    """
    # 1. Postgres — всегда
    await _db_save(chat_id, role, text)

    # 2. Redis — обновляем горячий кэш
    cached = await _redis_get(chat_id)
    history = cached if cached is not None else []
    history.append({"role": role, "content": text})

    # 3. Авто-сжатие при переполнении
    history = await _maybe_compress(chat_id, history)

    await _redis_set(chat_id, history)


async def clear_history(chat_id: int) -> None:
    """Очищает Redis. Postgres-история сохраняется (аудит)."""
    redis = await get_redis()
    await redis.delete(_key(chat_id))

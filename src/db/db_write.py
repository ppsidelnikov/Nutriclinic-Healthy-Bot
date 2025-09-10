from db.models import MessageLog, FoodModelAnswerLog, Ingredient
import json
from aiogram.types import Message, CallbackQuery
from db.db import AsyncSessionLocal

async def insert_message_log(
        session, 
        message_id=None,
        user_id=None, 
        user_name=None,
        user_nickname=None,
        message_dttm=False,
        message_txt=None,
        chat_id=None,
        message_content=None,
        ):
    log_entry = MessageLog(
        chat_id=chat_id,
        user_id=user_id,
        user_name=user_name,
        user_nickname=user_nickname,
        message_dttm=message_dttm,
        message_txt=message_txt,
        message_content=message_content,
        message_id=message_id
        )
    session.add(log_entry)
    await session.commit()


async def insert_food_model_answer_log(
        session,
        *,
        chat_id: str | None = None,
        message_id: str | None = None,
        model_name: str | None = None,
        token_input: int | None = None,
        token_output: int | None = None,
        request_price: float | None = None,
        payload: dict | None = None,
    ) -> None:
    """
    Writes one row to food_model_answer_log.
    payload is serialized into model_answer (string) for compatibility and also into payload_json if available.
    """
    payload_str = None
    try:
        if payload is not None:
            payload_str = json.dumps(payload, ensure_ascii=False)
    except Exception:
        payload_str = None

    entry = FoodModelAnswerLog(
        chat_id=chat_id,
        message_id=message_id,
        model_name=model_name,
        model_answer=payload_str,
        token_input=token_input,
        token_output=token_output,
        request_price=request_price,
    )
    # If the model has payload_json column, set it dynamically to avoid schema coupling
    if hasattr(entry, "payload_json") and payload is not None:
        setattr(entry, "payload_json", payload)

    session.add(entry)
    await session.commit()


async def insert_message_log_from_message(
        session,
        message: Message,
        *,
        message_txt_override: str | None = None,
        message_content: str | None = None,
    ) -> None:
    """Convenience wrapper to persist a Telegram Message into MessageLog."""
    await insert_message_log(
        session,
        message_id=str(message.message_id) if getattr(message, "message_id", None) is not None else None,
        user_id=str(message.from_user.id) if message.from_user else None,
        user_name=str(message.from_user.full_name) if message.from_user else None,
        user_nickname=str(message.from_user.username) if (message.from_user and message.from_user.username) else None,
        message_dttm=str(message.date.replace(tzinfo=None)) if getattr(message, "date", None) else None,
        message_txt=message_txt_override if message_txt_override is not None else (message.text or message.caption),
        chat_id=str(message.chat.id) if getattr(message, "chat", None) else None,
        message_content=message_content,
    )


async def insert_message_log_from_callback(
        session,
        cb: CallbackQuery,
        *,
        message_content: str | None = None,
    ) -> None:
    """Persist a CallbackQuery as a MessageLog row (stores data in message_txt)."""
    txt = cb.data if getattr(cb, "data", None) else None
    msg = cb.message
    await insert_message_log(
        session,
        message_id=str(msg.message_id) if msg else None,
        user_id=str(cb.from_user.id) if cb.from_user else None,
        user_name=str(cb.from_user.full_name) if cb.from_user else None,
        user_nickname=str(cb.from_user.username) if (cb.from_user and cb.from_user.username) else None,
        message_dttm=str(msg.date.replace(tzinfo=None)) if msg and getattr(msg, "date", None) else None,
        message_txt=txt,
        chat_id=str(msg.chat.id) if msg and getattr(msg, "chat", None) else None,
        message_content=message_content,
    )


async def answer_and_log(message: Message, text: str, **kwargs) -> Message:
    """
    Send a Telegram message and log the sent message into MessageLog.
    Returns the sent Message.
    """
    sent = await message.answer(text, **kwargs)
    try:
        async with AsyncSessionLocal() as session:
            await insert_message_log_from_message(session, sent)
    except Exception as e:
        print("answer_and_log logging error:", repr(e))
    return sent


def _normalize_ingredient_name(name: str | None) -> str:
    return (name or "").strip().lower()


async def upsert_ingredient(
        session,
        *,
        name: str,
        calories_kcal: float | None = None,
        protein_g: float | None = None,
        fat_g: float | None = None,
        carbs_g: float | None = None,
    ) -> None:
    """
    Insert or update an Ingredient by name_normalized.
    Nutrition values are per 100 g if provided.
    """
    norm = _normalize_ingredient_name(name)
    if not norm:
        return

    existing = await session.execute(
        (
            Ingredient.__table__.select()
            .where(Ingredient.name_normalized == norm)
            .limit(1)
        )
    )
    row = existing.fetchone()

    if row is None:
        item = Ingredient(
            name=name.strip(),
            name_normalized=norm,
            calories_kcal=calories_kcal,
            protein_g=protein_g,
            fat_g=fat_g,
            carbs_g=carbs_g,
        )
        session.add(item)
    else:
        await session.execute(
            Ingredient.__table__.update()
            .where(Ingredient.name_normalized == norm)
            .values(
                name=name.strip(),
                calories_kcal=calories_kcal if calories_kcal is not None else row["calories_kcal"],
                protein_g=protein_g if protein_g is not None else row["protein_g"],
                fat_g=fat_g if fat_g is not None else row["fat_g"],
                carbs_g=carbs_g if carbs_g is not None else row["carbs_g"],
            )
        )

    await session.commit()
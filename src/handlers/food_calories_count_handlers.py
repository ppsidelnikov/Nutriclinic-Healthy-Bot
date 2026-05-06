import asyncio
import traceback
import io
import base64
import re
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Optional
from aiogram import Router, F
from aiogram.types import Message
from aiogram.enums import ChatAction
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from db.db_write import insert_message_log, insert_food_model_answer_log, answer_and_log
from db.db import AsyncSessionLocal
from db.minio_io import ensure_bucket, upload_file
from services.yandex_gpt import get_answer_from_gpt_text, calc_price
from services.chat_history import get_history, add_message
from services.user_profile import get_user_profile, format_profile_context
from services.rag import search_knowledge, format_rag_context
from services.chat_gpt_api import async_get_dish_ingredients, async_identify_ingredients

router = Router(name="gpt_answer")

MODEL = "gpt-4.1"

JSON_BLOCK_RX = re.compile(r"\{.*\}", re.DOTALL)


def extract_json(text: str) -> Optional[dict]:
    if not text:
        return None
    m = JSON_BLOCK_RX.search(text)
    if not m:
        return None
    raw = m.group(0)
    try:
        return json.loads(raw)
    except Exception:
        try:
            return json.loads(raw.strip("` \n"))
        except Exception:
            return None


def fmt_total(title: str, t: dict) -> str:
    return (
        f"<b>{title}</b>\n"
        f"Калории: {round(t['kcal'])} ккал\n"
        f"Белки: {t['protein']:.1f} г\n"
        f"Жиры: {t['fat']:.1f} г\n"
        f"Углеводы: {t['carbs']:.1f} г"
    )


async def process_photo(message: Message):
    tg_file = None
    ensure_bucket()
    if message.photo:
        tg_file = message.photo[-1]
        file_id = tg_file.file_id
        filename_hint = f"{tg_file.file_unique_id}.jpg"
    elif message.document and message.document.mime_type and message.document.mime_type.startswith("image/"):
        tg_file = message.document
        file_id = tg_file.file_id
        filename_hint = tg_file.file_name or f"{tg_file.file_unique_id}.bin"

    if tg_file is None:
        raise ValueError("В сообщении не найдено изображение")

    buf = io.BytesIO()
    await message.bot.download(tg_file, destination=buf)
    data = buf.getvalue()
    buf.seek(0)
    img_bytes = buf.read()

    ext = Path(filename_hint).suffix or ".bin"
    key = f"chat/{message.chat.id}/msg/{message.message_id}/{file_id}{ext}"

    with NamedTemporaryFile(delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        uploaded_key = upload_file(tmp_path, key)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    return base64.b64encode(img_bytes).decode("utf-8"), uploaded_key


class AnalyzeDish(StatesGroup):
    waiting_for_photo = State()


async def _state_timeout(state: FSMContext, message: Message, expected_state: State, seconds: int = 60):
    await asyncio.sleep(seconds)
    if await state.get_state() == expected_state:
        await state.clear()
        await message.answer("Время ожидания истекло. Попробуйте снова командой /analyze_dish.")


async def run_photo_analysis(message: Message, *, b64: str, user_prompt: Optional[str]) -> None:
    """V6 двухпроходный pipeline (см. §3.1 диссертации):
       шаг 1 — модель сама распознаёт ингредиенты;
       шаг 2 — оценка КБЖУ с распознанным списком как hint.
    """
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    # Шаг 1: идентификация состава (короткий vision-вызов)
    try:
        ident_tokens, ingredients_hint = await async_identify_ingredients(b64, MODEL)
    except Exception:
        # Fallback: если шаг идентификации упал, идём в одиночный V1
        ident_tokens, ingredients_hint = ([0, 0], "")

    # Промежуточный сигнал пользователю — UX-улучшение, латентность V6 ≈ 6 сек
    if ingredients_hint:
        await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    # Шаг 2: основная оценка КБЖУ с подсказкой
    tokens, llm_text = await async_get_dish_ingredients(
        b64, user_prompt, MODEL, ingredients_hint=ingredients_hint
    )

    # Суммируем токены двух вызовов для аудита стоимости
    tokens = [tokens[0] + ident_tokens[0], tokens[1] + ident_tokens[1]]

    parsed = extract_json(llm_text)
    if not parsed:
        await message.answer("Не удалось распознать структуру блюда. Попробуйте фото покрупнее.")
        return

    # Извлекаем плоский V6-формат: dish_ru/dish_en/kcal/protein_g/fat_g/carbs_g.
    # Если модель вернула старый вложенный формат — берём что есть, но без КБЖУ.
    if "kcal" in parsed:
        dish_name    = (parsed.get("dish_en") or "").strip()
        dish_name_ru = (parsed.get("dish_ru") or "").strip()
        portion_grams = float(parsed.get("portion_grams") or 0)
        ingredients  = parsed.get("ingredients") or []
        model_kcal   = {
            "kcal":    float(parsed.get("kcal", 0)),
            "protein": float(parsed.get("protein_g", 0)),
            "fat":     float(parsed.get("fat_g", 0)),
            "carbs":   float(parsed.get("carbs_g", 0)),
        }
    else:
        dish_name    = (parsed.get("en", {}).get("dish") or "").strip()
        dish_name_ru = (parsed.get("ru", {}).get("dish") or "").strip()
        portion_grams = float(parsed.get("en", {}).get("portion_grams") or 0)
        ingredients  = parsed.get("en", {}).get("ingredients") or []
        model_kcal   = None

    if not model_kcal:
        await answer_and_log(message, "Модель не вернула оценку КБЖУ. Попробуйте другое фото.")
        return

    # Логируем результат в БД (только данные V6, без FatSecret)
    try:
        payload = {
            "dish_detected_en": dish_name,
            "dish_detected_ru": dish_name_ru,
            "portion_grams":    portion_grams,
            "ingredients":      ingredients,
            "model_estimate":   model_kcal,
            "model": {
                "selected": MODEL,
                "tokens":   tokens,
            },
        }
        async with AsyncSessionLocal() as session:
            await insert_food_model_answer_log(
                session,
                chat_id=str(message.chat.id),
                message_id=str(message.message_id),
                model_name=MODEL,
                token_input=int(tokens[0]) if tokens and len(tokens) > 0 else None,
                token_output=int(tokens[1]) if tokens and len(tokens) > 1 else None,
                request_price=calc_price(
                    MODEL,
                    int(tokens[0]) if tokens and len(tokens) > 0 else 0,
                    int(tokens[1]) if tokens and len(tokens) > 1 else 0,
                ),
                payload=payload,
            )
    except Exception as e:
        print("food_model_answer_log write error:", repr(e))

    # Финальный ответ пользователю — чистый V6 (только оценка модели, без FatSecret).
    parts = [
        f"🍽 <b>{dish_name_ru or dish_name or 'Блюдо'}</b>",
        f"Вес порции: {int(portion_grams) if portion_grams else '—'} г",
        fmt_total("КБЖУ", model_kcal),
    ]
    await answer_and_log(message, "\n\n".join(parts), parse_mode="HTML")


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Операция отменена.")


@router.message(Command("analyze_dish"))
async def cmd_analyze_dish(message: Message, state: FSMContext):
    await state.set_state(AnalyzeDish.waiting_for_photo)
    await message.answer("Отправьте фото блюда!")
    asyncio.create_task(_state_timeout(state, message, AnalyzeDish.waiting_for_photo, 60))


@router.message(
    AnalyzeDish.waiting_for_photo,
    F.photo | (F.document & F.document.mime_type.startswith("image/"))
)
async def handle_photo_in_state(message: Message, state: FSMContext):
    await state.clear()
    try:
        await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
        b64, minio_key = await process_photo(message)
        user_prompt = (message.caption or "").strip() or None

        try:
            async with AsyncSessionLocal() as session:
                await insert_message_log(
                    session,
                    str(message.message_id),
                    str(message.from_user.id),
                    str(message.from_user.full_name),
                    str(message.from_user.username),
                    str(message.date.replace(tzinfo=None)),
                    user_prompt,
                    str(message.chat.id),
                    minio_key,
                )
        except Exception as e:
            print("save_message_log error:", repr(e))

        await run_photo_analysis(message, b64=b64, user_prompt=user_prompt)

    except Exception as e:
        await answer_and_log(message, "Не удалось обработать фото. Попробуйте ещё раз.")
        print("handle_photo_in_state error:\n", "".join(traceback.format_exception(type(e), e, e.__traceback__)))


@router.message()
async def answer_gpt(message: Message):
    try:
        if message.text and not message.text.startswith("/"):
            await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)

            chat_id = message.chat.id
            user_id = str(message.from_user.id)

            # История, профиль и RAG-поиск — параллельно
            history, profile, rag_chunks = await asyncio.gather(
                get_history(chat_id),
                get_user_profile(user_id),
                search_knowledge(message.text, top_k=3),
            )
            user_context = format_profile_context(profile)
            rag_context  = format_rag_context(rag_chunks)

            gpt_answer, usage = await get_answer_from_gpt_text(
                message.text,
                history=history,
                user_context=user_context,
                rag_context=rag_context,
            )

            # Сохраняем оба сообщения в историю
            await add_message(chat_id, "user", message.text)
            await add_message(chat_id, "assistant", gpt_answer)

            # Логируем токены и стоимость
            try:
                async with AsyncSessionLocal() as session:
                    await insert_food_model_answer_log(
                        session,
                        chat_id=str(chat_id),
                        message_id=str(message.message_id),
                        model_name=usage["model"],
                        token_input=usage["input_tokens"],
                        token_output=usage["output_tokens"],
                        request_price=usage["price_rub"],
                        payload={"type": "text_query", "query": message.text[:500]},
                    )
            except Exception as e:
                print("text_query log error:", repr(e))

            await answer_and_log(message, gpt_answer)
            return
        await answer_and_log(message, "Отправьте фото блюда или напишите вопрос нутрициологу.")
    except Exception as e:
        await answer_and_log(message, "Не удалось обработать сообщение. Попробуйте ещё раз.")
        print("GPT handler error:", repr(e))

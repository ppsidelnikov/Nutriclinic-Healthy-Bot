import asyncio
import traceback
from pathlib import Path
import io
import base64
import re
import json
import os
from tempfile import NamedTemporaryFile
from typing import Optional
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.enums import ChatAction
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from db.db_write import insert_message_log, insert_food_model_answer_log, upsert_ingredient, answer_and_log
from db.db import AsyncSessionLocal

from db.minio_io import ensure_bucket, upload_file, presigned_get_url
from services.calculate_token_price import get_model_call_price

from services.yandex_gpt import get_answer_from_gpt_text
from services.chat_gpt_api import async_get_dish_ingredients
from services.fatsecret_api_cached import (
    get_fatsecret_token,
    search_by_dish_name_cached,
    search_by_ingredients_cached,
    total_by_dish_search_cached,
    total_by_ingredients_search_cached,
    pick_best_food,
)
from services.fatsecret_utils import parse_food_description

router = Router(name="gpt_answer")  

MODELS = {
    'gpt-5': 'ChatGPT 5',
    'gpt-5-mini': 'ChatGPT 5 Mini',
    'gpt-5-nano': 'ChatGPT 5 Nano',
    'gpt-4.1': 'ChatGPT 4.1',
    'gpt-4.1-mini': 'ChatGPT 4.1 Mini',
    'gpt-4.1-nano': 'ChatGPT 4.1 Nano',
    'gpt-4o': 'ChatGPT 4o',
    'gpt-4o-mini': 'ChatGPT 4o Mini',
    'gemini-2.5-pro': 'Gemini 2.5 Pro',
    'gemini-2.5-flash': 'Gemini 2.5 Flash',
    'o4-mini': 'O4 Mini',
    'o3': 'O3',
    'o3-pro': 'O3 Pro',
}

RATING_VALUES = [1, 2, 3, 4, 5]


def build_models_kb() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for model_key, title in MODELS.items():
        kb.button(text=title, callback_data=f"model:{model_key}")
    kb.adjust(1)
    return kb

def build_rating_kb() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for v in RATING_VALUES:
        kb.button(text=str(v), callback_data=f"rate:{v}")
        kb.adjust(5)
    return kb

JSON_BLOCK_RX = re.compile(r"\{.*\}", re.DOTALL)

def extract_json(text: str) -> Optional[dict]:
    """
    Пытаемся найти JSON в ответе модели.
    """
    if not text:
        return None
    m = JSON_BLOCK_RX.search(text)
    if not m:
        return None
    raw = m.group(0)
    try:
        return json.loads(raw)
    except Exception:
        # иногда модель оборачивает в ```json ... ```
        raw = raw.strip("` \n")
        return json.loads(raw)
    
def fmt_total(title: str, t: dict) -> str:
    return (
        f"<b>{title}</b>\n"
        f"Калории: {round(t['kcal'])} ккал\n"
        f"Белки: {t['protein']:.1f} г\n"
        f"Жиры: {t['fat']:.1f} г\n"
        f"Углеводы: {t['carbs']:.1f} г"
    )


async def process_photo(message: Message) -> str:
    """
    Достаёт изображение из сообщения Telegram и возвращает base64-строку.
    Поддерживает: message.photo (любое качество) и document с image/*.
    Ничего на диск не пишет — работает только в памяти.
    """
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
    waiting_for_model_choice = State()
    waiting_for_rating = State()

async def _state_timeout(state: FSMContext, message: Message, expected_state: State, seconds: int = 30):
    await asyncio.sleep(seconds)
    if await state.get_state() == expected_state:
        await state.clear()
        await message.answer("Время ожидания истекло. Попробуйте снова командой /analyze_dish.")

async def run_photo_analysis_core(message: Message, *, b64: str, user_prompt: Optional[str], selected_model: str) -> None:
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    tokens, llm_text = await async_get_dish_ingredients(b64, user_prompt, selected_model)
    price_for_model_call = get_model_call_price(selected_model, tokens[0], tokens[1])
    await answer_and_log(
        message,
        f"Модель: <b>{selected_model}</b>\n"
        f"Ответ модели:\n{llm_text}\n\nТокены: {tokens}\nСтоимость запроса: {price_for_model_call}",
        parse_mode="HTML",
    )

    parsed = extract_json(llm_text)
    if not parsed:
        await message.answer("Не удалось распознать структуру блюда. Попробуйте ещё раз, фото покрупнее.")
        return

    dish_name = (parsed.get("en", {}).get("dish") or "").strip()
    dish_name_ru = (parsed.get("ru", {}).get("dish") or "").strip()
    portion_grams = float(parsed.get("en", {}).get("portion_grams") or 0)
    ingredients = parsed.get("en", {}).get("ingredients") or []

    await answer_and_log(message, f"Распознано:\n{dish_name}, {portion_grams} г, {ingredients}")

    if not ingredients:
        await answer_and_log(message, "Модель не распознала ингредиенты. Попробуйте другое фото или ракурс.")
        return

    token = get_fatsecret_token()
    dish_results, dish_hit = await search_by_dish_name_cached(token, dish_name, max_results=5)
    # Ответ Telegram ограничен ~4096 символами. Покажем краткую сводку вместо всего JSON.
    try:
        dish_cnt = len(dish_results or [])
        top_dish = (dish_results[0].get("food_name") if dish_results else None)
        await answer_and_log(
            message,
            f"Результаты по блюду: {dish_cnt} найдено" + (f", лучший: {top_dish}" if top_dish else "")
        )
    except Exception:
        await answer_and_log(message, "Результаты по блюду получены.")
    total_A = await total_by_dish_search_cached(dish_results, portion_grams) if portion_grams > 0 else None

    ing_results_map, ing_hits = await search_by_ingredients_cached(token, ingredients, max_results=3)
    try:
        ing_total = sum(len(v) for v in (ing_results_map or {}).values())
        first_ing = next(iter(ing_results_map)) if ing_results_map else None
        await answer_and_log(
            message,
            f"Результаты по ингредиентам: {ing_total} вариантов" + (f", пример: {first_ing}" if first_ing else "")
        )
    except Exception:
        await answer_and_log(message, "Результаты по ингредиентам получены.")
    total_B = await total_by_ingredients_search_cached(ing_results_map, ingredients)

    # Persist ingredients (per-100g where possible from best matched foods)
    try:
        async with AsyncSessionLocal() as session:
            for name, foods in (ing_results_map or {}).items():
                best = None
                try:
                    best = pick_best_food(foods)
                except Exception:
                    best = None
                nutr = parse_food_description(best.get("food_description", "")) if best else {}
                await upsert_ingredient(
                    session,
                    name=name,
                    calories_kcal=(nutr or {}).get("kcal_100g"),
                    protein_g=(nutr or {}).get("protein_100g"),
                    fat_g=(nutr or {}).get("fat_100g"),
                    carbs_g=(nutr or {}).get("carbs_100g"),
                )
    except Exception as e:
        print("ingredient upsert error:", repr(e))

    # Prepare logging payload
    cache_ratio = None
    try:
        total_ings = len(ingredients or [])
        cache_hits = sum(1 for k, v in (ing_hits or {}).items() if v)
        if total_ings > 0:
            cache_ratio = cache_hits / total_ings
    except Exception:
        cache_ratio = None

    payload = {
        "dish_detected_en": dish_name,
        "dish_detected_ru": dish_name_ru,
        "portion_grams": portion_grams,
        "ingredients": ingredients,
        "fatsecret": {
            "dish_search_used_cache": bool(dish_hit),
            "ingredient_cache_map": ing_hits,
            "ingredient_cache_ratio": cache_ratio,
        },
        "totals": {
            "by_dish": total_A,
            "by_ingredients": total_B,
        },
        "model": {
            "selected": selected_model,
            "tokens": tokens,
            "price": price_for_model_call,
        }
    }

    try:
        async with AsyncSessionLocal() as session:
            await insert_food_model_answer_log(
                session,
                chat_id=str(message.chat.id),
                message_id=str(message.message_id),
                model_name=selected_model,
                token_input=int(tokens[0]) if tokens and len(tokens) > 0 else None,
                token_output=int(tokens[1]) if tokens and len(tokens) > 1 else None,
                request_price=float(price_for_model_call) if price_for_model_call is not None else None,
                payload=payload,
            )
    except Exception as e:
        print("food_model_answer_log write error:", repr(e))

    parts = []
    parts.append(
        "Финальное сообщение:\n\n"
        f"🍽 <b>Опознано блюдо:</b> {dish_name_ru or '—'}\n"
        f"Вес порции: {int(portion_grams) if portion_grams else '—'} г"
    )
    if total_A:
        parts.append(fmt_total("Метод A — по названию блюда", total_A))
    else:
        parts.append("<b>Метод A — по названию блюда</b>\nНет подходящих данных для расчёта.")
    if total_B:
        parts.append(fmt_total("Метод B — по ингредиентам", total_B))
    else:
        parts.append("<b>Метод B — по ингредиентам</b>\nНет подходящих данных для расчёта.")

    await answer_and_log(message, "\n\n".join(parts), parse_mode="HTML")

async def save_message_log(message: Message, *, user_prompt: Optional[str], file_key: Optional[str]) -> None:
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
                file_key,
                )
    except Exception as e:
        print("save_message_log error:", repr(e))

@router.message(Command("analyze_dish"))
async def cmd_analyze_dish(message: Message, state: FSMContext):
    await state.set_state(AnalyzeDish.waiting_for_photo)
    await message.answer(
        "Отправляйте фото блюда!"
    )
    asyncio.create_task(_state_timeout(state, message, AnalyzeDish.waiting_for_photo, 30))
    


@router.message(
    AnalyzeDish.waiting_for_photo,
    F.photo | (F.document & F.document.mime_type.startswith("image/"))
)
async def handle_photo_in_state(message: Message, state: FSMContext):
    try:    
        await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
        b64, minio_key = await process_photo(message)
        user_prompt = (message.caption or "").strip() or None

        await state.set_state(AnalyzeDish.waiting_for_model_choice)
        await state.update_data(b64=b64, minio_key=minio_key, user_prompt=user_prompt)

        kb = build_models_kb()
        await message.answer("Выберите модель для анализа:", reply_markup=kb.as_markup())

        asyncio.create_task(_state_timeout(state, message, AnalyzeDish.waiting_for_model_choice, 30))
        
    except Exception as e:
        await state.clear()
        await answer_and_log(message, "Не удалось обработать фото. Попробуйте ещё раз.")
        error_text = "".join(traceback.format_exception(type(e), e, e.__traceback__))
        print("handle_photo_in_state full error:\n", error_text)

@router.callback_query(AnalyzeDish.waiting_for_model_choice, F.data.startswith("model:"))
async def on_model_choice(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    model_key = cb.data.split(":", 1)[1]
    model_name = MODELS.get(model_key)
    if not model_name:
        await answer_and_log(cb.message, "Неизвестная модель. Попробуйте снова командой /analyze_dish.")
        await state.clear()
        return

    data = await state.get_data()
    b64 = data.get("b64")
    user_prompt = data.get("user_prompt")
    try:
        await run_photo_analysis_core(cb.message, b64=b64, user_prompt=user_prompt, selected_model=model_key)
    except Exception as e:
        await state.clear()
        await answer_and_log(cb.message, "Не удалось обработать фото. Попробуйте ещё раз.")
        error_text = "".join(traceback.format_exception(type(e), e, e.__traceback__))
        print("analysis_core error:\n", error_text)
    try:
        await save_message_log(cb.message, user_prompt=user_prompt, file_key=data.get("minio_key"))
    except Exception as e:
        print("log error:", repr(e))

    await state.set_state(AnalyzeDish.waiting_for_rating)
    rating_kb = build_rating_kb()
    await answer_and_log(cb.message, "Оцените, насколько точно модель оценила блюдо:", reply_markup=rating_kb.as_markup())

    asyncio.create_task(_state_timeout(state, cb.message, AnalyzeDish.waiting_for_rating, 30))


@router.callback_query(AnalyzeDish.waiting_for_rating, F.data.startswith("rate:"))
async def on_rating(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    try:
        rating = int(cb.data.split(":", 1)[1])
    except Exception:
        rating = None

    if rating and rating in RATING_VALUES:
        await answer_and_log(cb.message, f"Спасибо! Ваша оценка: {rating}/5")
    else:
        await answer_and_log(cb.message, "Некорректная оценка.")

    await state.clear()


@router.message()
async def answer_gpt(message: Message):
    try:

        if message.text and not message.text.startswith("/"):
            await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
            gpt_answer = await get_answer_from_gpt_text(message.text)
            await answer_and_log(message, gpt_answer)
            return

        # Фолбэк
        await answer_and_log(message, "Пришлите фото блюда или текстовый вопрос.")

    except Exception as e:
        await answer_and_log(message, "Не удалось обработать сообщение. Попробуйте ещё раз.")
        # Логирование на ваше усмотрение
        print("GPT handler error:", repr(e))


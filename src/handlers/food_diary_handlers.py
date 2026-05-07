"""
Обработчики дневника питания: /today, /add, inline-кнопки выбора приёма пищи
после анализа фото и удаление записей.

Контракт callback_data:
  - "diary_save:<meal_type>:<temp_id>"  — сохранить последнюю запись из state
  - "diary_skip:<temp_id>"               — не сохранять (просто закрыть кнопки)
  - "diary_del:<entry_id>"               — удалить запись из БД
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import asyncio

from aiogram import Router, F
from aiogram.enums import ChatAction
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)


class AddDish(StatesGroup):
    """Команда /add: ждём от пользователя фото или текстовое описание."""
    waiting_for_input = State()

from services.food_diary import (
    add_entry, delete_entry, get_today, format_today,
    get_daily_progress, format_progress_line, format_macro_tips,
    get_streak, get_week_summary, format_week, delete_last_entry,
    get_top_dishes, get_entry_by_id,
    MEAL_LABELS, MEAL_ORDER,
)
from services.user_profile import get_user_profile
from services.food_parser import parse_food_text as _parse_food_text
from services.photo_recognition import client as openai_client
from config.config import config

router = Router(name="food_diary")
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Inline-клавиатура для сохранения после анализа фото
# ──────────────────────────────────────────────────────────────────────────────
def build_meal_keyboard(temp_id: str) -> InlineKeyboardMarkup:
    """Кнопки выбора приёма пищи после анализа фото."""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=MEAL_LABELS["breakfast"], callback_data=f"diary_save:breakfast:{temp_id}"),
            InlineKeyboardButton(text=MEAL_LABELS["lunch"],     callback_data=f"diary_save:lunch:{temp_id}"),
        ],
        [
            InlineKeyboardButton(text=MEAL_LABELS["dinner"],    callback_data=f"diary_save:dinner:{temp_id}"),
            InlineKeyboardButton(text=MEAL_LABELS["snack"],     callback_data=f"diary_save:snack:{temp_id}"),
        ],
        [
            InlineKeyboardButton(text="❌ Не сохранять", callback_data=f"diary_skip:{temp_id}"),
        ],
    ])
    return kb


def build_today_keyboard(snapshot: dict) -> Optional[InlineKeyboardMarkup]:
    """Кнопки под каждой записью /today: удалить и повторить."""
    rows = []
    for meal_type in MEAL_ORDER:
        for item in snapshot["by_meal"].get(meal_type, []):
            label = f"🗑 {MEAL_LABELS[meal_type].split()[1]}: {item['dish_name'][:22]}"
            rows.append([
                InlineKeyboardButton(text=label, callback_data=f"diary_del:{item['id']}"),
                InlineKeyboardButton(text="🔁",   callback_data=f"diary_rep:{item['id']}"),
            ])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def build_saved_keyboard(top_dishes: list[dict]) -> InlineKeyboardMarkup:
    """Список авто-сохранёнок: каждая — отдельная кнопка."""
    rows = []
    for i, d in enumerate(top_dishes):
        label = f"{d['dish_name'][:35]} — {d['avg_kcal']:.0f} ккал ×{d['count']}"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"saved_pick:{i}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ──────────────────────────────────────────────────────────────────────────────
# In-memory кэш «последний анализ фото» — между показом КБЖУ и кликом по кнопке
# ──────────────────────────────────────────────────────────────────────────────
# В продакшене на множестве реплик это надо вынести в Redis. Для одного инстанса
# и интерактивной нагрузки достаточно in-memory с авто-очисткой по TTL.
_pending_entries: dict[str, dict] = {}


def remember_entry(temp_id: str, payload: dict) -> None:
    _pending_entries[temp_id] = payload
    # простое ограничение на размер кэша
    if len(_pending_entries) > 1000:
        # выкидываем 100 старейших
        for k in list(_pending_entries.keys())[:100]:
            _pending_entries.pop(k, None)


async def _post_add_footer(user_id: str) -> str:
    """Стандартный «хвост» после успешного добавления записи: прогресс + подсказки."""
    profile = await get_user_profile(user_id)
    target_kcal = float(profile.daily_calories_target) if profile and profile.daily_calories_target else None
    progress = await get_daily_progress(user_id, target_kcal)
    tail = format_progress_line(progress)
    tips = format_macro_tips(progress)
    if tips:
        tail += "\n\n" + tips
    return tail


# ──────────────────────────────────────────────────────────────────────────────
# Хэндлеры в состоянии AddDish (после /add без аргументов)
# Должны быть зарегистрированы ДО общих хэндлеров — сначала проверим state.
# ──────────────────────────────────────────────────────────────────────────────
@router.message(
    AddDish.waiting_for_input,
    F.photo | (F.document & F.document.mime_type.startswith("image/")),
)
async def add_via_photo(message: Message, state: FSMContext):
    """В состоянии /add принимаем фото — анализ V6 + кнопки сохранения."""
    await state.clear()
    # Импорт здесь, чтобы избежать циклических импортов на уровне модуля
    from handlers.food_calories_count_handlers import process_photo, run_photo_analysis

    try:
        await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
        b64, _ = await process_photo(message)
        user_prompt = (message.caption or "").strip() or None
        await run_photo_analysis(
            message, b64=b64, user_prompt=user_prompt, with_save_buttons=True
        )
    except Exception as e:
        await message.answer("Не удалось обработать фото. Попробуйте ещё раз.")
        print("add_via_photo error:", repr(e))


@router.message(AddDish.waiting_for_input)
async def add_via_text(message: Message, state: FSMContext):
    """В состоянии /add принимаем текст — парсинг + кнопки сохранения."""
    await state.clear()
    text = (message.text or "").strip()
    if not text:
        await message.answer("Не понял. Отправь фото или текст с описанием еды.")
        return
    await _process_text_for_diary(message, text)


# ──────────────────────────────────────────────────────────────────────────────
# Команды
# ──────────────────────────────────────────────────────────────────────────────
@router.message(Command("today"))
async def cmd_today(message: Message):
    user_id = str(message.from_user.id)
    profile = await get_user_profile(user_id)
    target_kcal = float(profile.daily_calories_target) if profile and profile.daily_calories_target else None
    progress = await get_daily_progress(user_id, target_kcal)
    streak = await get_streak(user_id)
    text = format_today(progress, streak=streak)
    kb = build_today_keyboard(progress)
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.message(Command("yesterday"))
async def cmd_yesterday(message: Message):
    """Сводка за вчерашний день — без интерактивного редактирования."""
    user_id = str(message.from_user.id)
    profile = await get_user_profile(user_id)
    target_kcal = float(profile.daily_calories_target) if profile and profile.daily_calories_target else None
    progress = await get_daily_progress(user_id, target_kcal, days_ago=1)
    text = format_today(progress, streak=0, title="📊 Вчера")
    await message.answer(text, parse_mode="HTML")


@router.message(Command("week"))
async def cmd_week(message: Message):
    """Сводка за последние 7 дней."""
    user_id = str(message.from_user.id)
    profile = await get_user_profile(user_id)
    target_kcal = float(profile.daily_calories_target) if profile and profile.daily_calories_target else None
    week = await get_week_summary(user_id, days_back=7)
    await message.answer(format_week(week, target_kcal=target_kcal), parse_mode="HTML")


@router.message(Command("saved"))
async def cmd_saved(message: Message):
    """Сохранёнки: список самых частых блюд за 14 дней с быстрым добавлением."""
    user_id = str(message.from_user.id)
    top = await get_top_dishes(user_id, days_back=14, limit=8)
    if not top:
        await message.answer(
            "Сохранёнок пока нет — они появятся автоматически из твоего дневника.\n"
            "Записывай еду через /add — самые частые блюда будут доступны здесь."
        )
        return

    # Запоминаем список в pending, чтобы callback'и могли его взять
    temp_id = f"saved_{message.chat.id}_{message.message_id}"
    remember_entry(temp_id, {"saved_list": top})

    # Перевыпускаем клавиатуру с привязкой к temp_id
    rows = [
        [InlineKeyboardButton(
            text=f"{d['dish_name'][:35]} — {d['avg_kcal']:.0f} ккал ×{d['count']}",
            callback_data=f"saved_pick:{i}:{temp_id}",
        )]
        for i, d in enumerate(top)
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=rows)

    await message.answer(
        "<b>📌 Твои частые блюда</b>\n\n"
        "Нажми, чтобы добавить в дневник одним кликом:",
        reply_markup=kb,
        parse_mode="HTML",
    )


@router.message(Command("undo"))
async def cmd_undo(message: Message):
    """Удалить последнюю запись дневника."""
    user_id = str(message.from_user.id)
    deleted = await delete_last_entry(user_id)
    if not deleted:
        await message.answer("В дневнике нет записей — нечего удалять.")
        return
    meal_label = MEAL_LABELS.get(deleted["meal_type"], deleted["meal_type"])
    await message.answer(
        f"✓ Удалена последняя запись из {meal_label.lower()}: "
        f"<b>{deleted['dish_name']}</b> — {deleted['kcal']:.0f} ккал",
        parse_mode="HTML",
    )


@router.message(Command("add"))
async def cmd_add(message: Message, state: FSMContext):
    """Принимает фото или текст. Без аргументов — ждёт следующее сообщение."""
    text = (message.text or "").strip()
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        # Включаем режим ожидания: следующее фото или текст пойдут в /add
        await state.set_state(AddDish.waiting_for_input)
        await message.answer(
            "📝 Что ты съел? Отправь фото блюда или опиши текстом.\n\n"
            "Например:\n"
            "• <code>гречка 200г обед</code>\n"
            "• <code>булочка с маслом завтрак</code>\n"
            "• или просто фото тарелки",
            parse_mode="HTML",
        )
        return

    user_text = parts[1]
    user_id = str(message.from_user.id)
    await _process_text_for_diary(message, user_text)


async def _process_text_for_diary(message: Message, user_text: str) -> None:
    """Парсит текстовое описание еды через LLM и предлагает сохранить."""
    user_id = str(message.from_user.id)

    await message.bot.send_chat_action(message.chat.id, "typing")
    parsed = await _parse_food_text(user_text)
    if not parsed:
        await message.answer(
            "Не получилось разобрать описание. Попробуй формат: «название кол-во приём_пищи».")
        return

    # сохраняем в pending и показываем подтверждение с кнопками выбора meal_type
    temp_id = f"manual_{message.message_id}"
    remember_entry(temp_id, {**parsed, "source": "manual"})

    kb = build_meal_keyboard(temp_id)
    confirm = (
        f"Распознал: <b>{parsed['dish_name']}</b>"
        f"{', ' + str(int(parsed['portion_g'])) + ' г' if parsed.get('portion_g') else ''}\n"
        f"КБЖУ: {parsed['kcal']:.0f} ккал, "
        f"Б {parsed.get('protein_g', 0):.1f} / Ж {parsed.get('fat_g', 0):.1f} / У {parsed.get('carbs_g', 0):.1f}\n\n"
        f"Куда записать?"
    )
    # если в тексте уже указан приём — сразу сохраняем без вопроса
    if parsed.get("meal_type") in MEAL_LABELS:
        entry_id = await add_entry(telegram_id=user_id, **{**parsed, "source": "manual"})
        footer = await _post_add_footer(user_id)
        await message.answer(
            f"✓ Записано в {MEAL_LABELS[parsed['meal_type']].lower()}: "
            f"<b>{parsed['dish_name']}</b> — {parsed['kcal']:.0f} ккал\n\n"
            f"{footer}",
            parse_mode="HTML",
        )
        _pending_entries.pop(temp_id, None)
    else:
        await message.answer(confirm, parse_mode="HTML", reply_markup=kb)


# ──────────────────────────────────────────────────────────────────────────────
# Callback-обработчики (инлайн-кнопки)
# ──────────────────────────────────────────────────────────────────────────────
@router.callback_query(lambda c: c.data and c.data.startswith("diary_save:"))
async def cb_save(callback: CallbackQuery):
    parts = callback.data.split(":", 2)
    if len(parts) != 3:
        await callback.answer("Неверный формат")
        return
    _, meal_type, temp_id = parts
    if meal_type not in MEAL_LABELS:
        await callback.answer("Неизвестный приём пищи")
        return

    payload = _pending_entries.pop(temp_id, None)
    if not payload:
        await callback.answer("Запись уже сохранена или истёк срок ожидания")
        return

    user_id = str(callback.from_user.id)
    entry_id = await add_entry(
        telegram_id=user_id,
        meal_type=meal_type,
        dish_name=payload["dish_name"],
        kcal=payload["kcal"],
        portion_g=payload.get("portion_g"),
        protein_g=payload.get("protein_g"),
        fat_g=payload.get("fat_g"),
        carbs_g=payload.get("carbs_g"),
        source=payload.get("source", "photo"),
    )

    # снимаем клавиатуру и пишем подтверждение с прогрессом и подсказками
    await callback.message.edit_reply_markup(reply_markup=None)
    footer = await _post_add_footer(user_id)
    confirm_text = (
        f"✓ Добавлено в {MEAL_LABELS[meal_type].lower()}: "
        f"<b>{payload['dish_name']}</b> — {payload['kcal']:.0f} ккал\n\n"
        f"{footer}"
    )
    await callback.message.answer(confirm_text, parse_mode="HTML")
    await callback.answer("Сохранено")


@router.callback_query(lambda c: c.data and c.data.startswith("diary_skip:"))
async def cb_skip(callback: CallbackQuery):
    _, temp_id = callback.data.split(":", 1)
    _pending_entries.pop(temp_id, None)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Не сохранено")


@router.callback_query(lambda c: c.data and c.data.startswith("diary_rep:"))
async def cb_repeat(callback: CallbackQuery):
    """Повторить запись: копирует существующую запись на сегодня тем же приёмом пищи."""
    _, entry_id_str = callback.data.split(":", 1)
    try:
        entry_id = int(entry_id_str)
    except ValueError:
        await callback.answer("Неверный id")
        return

    user_id = str(callback.from_user.id)
    src = await get_entry_by_id(user_id, entry_id)
    if not src:
        await callback.answer("Запись не найдена")
        return

    new_id = await add_entry(
        telegram_id=user_id,
        meal_type=src["meal_type"],
        dish_name=src["dish_name"],
        kcal=src["kcal"],
        portion_g=src.get("portion_g"),
        protein_g=src.get("protein_g"),
        fat_g=src.get("fat_g"),
        carbs_g=src.get("carbs_g"),
        source="repeat",
    )
    footer = await _post_add_footer(user_id)
    await callback.message.answer(
        f"✓ Повторено в {MEAL_LABELS[src['meal_type']].lower()}: "
        f"<b>{src['dish_name']}</b> — {src['kcal']:.0f} ккал\n\n"
        f"{footer}",
        parse_mode="HTML",
    )
    await callback.answer("Добавлено")


@router.callback_query(lambda c: c.data and c.data.startswith("saved_pick:"))
async def cb_saved_pick(callback: CallbackQuery):
    """Клик по сохранёнке → показ кнопок выбора приёма пищи."""
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Неверный формат")
        return
    idx = int(parts[1])
    temp_id = parts[2]

    payload = _pending_entries.get(temp_id)
    if not payload or "saved_list" not in payload:
        await callback.answer("Список устарел, открой /saved заново")
        return
    saved_list = payload["saved_list"]
    if idx >= len(saved_list):
        await callback.answer("Запись не найдена")
        return

    dish = saved_list[idx]
    # сохраняем выбранный шаблон под отдельным ключом для следующего шага
    pick_id = f"savedpick_{callback.message.chat.id}_{callback.message.message_id}_{idx}"
    remember_entry(pick_id, {
        "dish_name": dish["dish_name"],
        "portion_g": dish.get("avg_portion_g"),
        "kcal":      dish["avg_kcal"],
        "protein_g": dish["avg_protein"],
        "fat_g":     dish["avg_fat"],
        "carbs_g":   dish["avg_carbs"],
        "source":    "saved",
    })
    kb = build_meal_keyboard(pick_id)
    await callback.message.answer(
        f"Добавить <b>{dish['dish_name']}</b> ({dish['avg_kcal']:.0f} ккал) в какой приём пищи?",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("diary_del:"))
async def cb_delete(callback: CallbackQuery):
    _, entry_id_str = callback.data.split(":", 1)
    try:
        entry_id = int(entry_id_str)
    except ValueError:
        await callback.answer("Неверный id")
        return

    user_id = str(callback.from_user.id)
    ok = await delete_entry(entry_id, user_id)
    if not ok:
        await callback.answer("Запись не найдена")
        return

    # перерисовываем сводку с актуальным прогрессом
    profile = await get_user_profile(user_id)
    target_kcal = float(profile.daily_calories_target) if profile and profile.daily_calories_target else None
    progress = await get_daily_progress(user_id, target_kcal)
    text = format_today(progress)
    kb = build_today_keyboard(progress)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer("Удалено")


# парсинг свободного текста вынесен в services/food_parser.py
# и импортируется выше как _parse_food_text

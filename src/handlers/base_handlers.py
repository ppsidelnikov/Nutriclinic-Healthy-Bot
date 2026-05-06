from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

from services.user_profile import get_user_profile, upsert_user_profile, format_profile_context
from services.chat_history import clear_history

router = Router(name="base")


# ─── FSM ────────────────────────────────────────────────────────────────────

class ProfileSetup(StatesGroup):
    name        = State()
    age         = State()
    gender      = State()
    weight      = State()
    height      = State()
    goal        = State()
    restrictions = State()


# ─── Keyboards ───────────────────────────────────────────────────────────────

def gender_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Мужской", callback_data="gender:male"),
        InlineKeyboardButton(text="Женский", callback_data="gender:female"),
    ]])


def goal_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Снизить вес",      callback_data="goal:weight_loss")],
        [InlineKeyboardButton(text="Набрать массу",    callback_data="goal:muscle_gain")],
        [InlineKeyboardButton(text="Поддержать форму", callback_data="goal:maintain")],
    ])


def skip_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Пропустить", callback_data="skip"),
    ]])


# ─── /start ──────────────────────────────────────────────────────────────────

@router.message(Command("start"))
async def cmd_start(message: Message):
    profile = await get_user_profile(str(message.from_user.id))
    if profile and profile.name:
        await message.answer(
            f"С возвращением, {profile.name}! 👋\n\n"
            "Я — твой персональный нутрициолог.\n\n"
            "Что умею:\n"
            "• /analyze_dish — анализ калорийности по фото\n"
            "• /profile — посмотреть / изменить свой профиль\n"
            "• Просто напиши вопрос — отвечу как нутрициолог"
        )
    else:
        await message.answer(
            "Привет! Я — твой персональный нутрициолог 🥗\n\n"
            "Что умею:\n"
            "• /analyze_dish — анализ калорийности блюда по фото\n"
            "• /profile — заполнить профиль для персональных советов\n"
            "• Просто напиши вопрос — отвечу как нутрициолог\n\n"
            "Рекомендую заполнить профиль командой /profile, чтобы советы были точнее."
        )


# ─── /help ───────────────────────────────────────────────────────────────────

@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "<b>Доступные команды:</b>\n\n"
        "/analyze_dish — отправить фото блюда и получить КБЖУ\n"
        "/profile — заполнить или обновить профиль\n"
        "/history_clear — очистить историю диалога\n"
        "/cancel — отменить текущее действие\n\n"
        "Или просто задай вопрос нутрициологу в чат.",
        parse_mode="HTML",
    )


# ─── /history_clear ──────────────────────────────────────────────────────────

@router.message(Command("history_clear"))
async def cmd_history_clear(message: Message):
    await clear_history(message.chat.id)
    await message.answer("История диалога очищена.")


# ─── /profile — просмотр ────────────────────────────────────────────────────

@router.message(Command("profile"))
async def cmd_profile(message: Message, state: FSMContext):
    profile = await get_user_profile(str(message.from_user.id))
    if profile:
        ctx = format_profile_context(profile)
        await message.answer(
            f"<b>Ваш профиль:</b>\n{ctx}\n\n"
            "Хотите обновить данные? Введите /profile_edit",
            parse_mode="HTML",
        )
    else:
        await message.answer(
            "Профиль ещё не заполнен. Давайте исправим! 🙂\n\n"
            "Как вас зовут?"
        )
        await state.set_state(ProfileSetup.name)


@router.message(Command("profile_edit"))
async def cmd_profile_edit(message: Message, state: FSMContext):
    await message.answer("Обновляем профиль. Как вас зовут?")
    await state.set_state(ProfileSetup.name)


# ─── FSM-шаги ────────────────────────────────────────────────────────────────

@router.message(ProfileSetup.name)
async def profile_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await message.answer("Сколько вам лет?", reply_markup=skip_kb())
    await state.set_state(ProfileSetup.age)


@router.message(ProfileSetup.age)
async def profile_age(message: Message, state: FSMContext):
    text = message.text.strip()
    if text.isdigit() and 5 <= int(text) <= 120:
        await state.update_data(age=int(text))
    await message.answer("Ваш пол:", reply_markup=gender_kb())
    await state.set_state(ProfileSetup.gender)


@router.callback_query(ProfileSetup.gender, F.data.startswith("gender:"))
async def profile_gender(callback: CallbackQuery, state: FSMContext):
    await state.update_data(gender=callback.data.split(":")[1])
    await callback.message.answer("Ваш текущий вес (кг)? Например: 75", reply_markup=skip_kb())
    await callback.answer()
    await state.set_state(ProfileSetup.weight)


@router.message(ProfileSetup.weight)
async def profile_weight(message: Message, state: FSMContext):
    text = message.text.strip().replace(",", ".")
    try:
        w = float(text)
        if 20 <= w <= 300:
            await state.update_data(weight_kg=w)
    except ValueError:
        pass
    await message.answer("Ваш рост (см)? Например: 175", reply_markup=skip_kb())
    await state.set_state(ProfileSetup.height)


@router.message(ProfileSetup.height)
async def profile_height(message: Message, state: FSMContext):
    text = message.text.strip().replace(",", ".")
    try:
        h = float(text)
        if 100 <= h <= 250:
            await state.update_data(height_cm=h)
    except ValueError:
        pass
    await message.answer("Ваша цель:", reply_markup=goal_kb())
    await state.set_state(ProfileSetup.goal)


@router.callback_query(ProfileSetup.goal, F.data.startswith("goal:"))
async def profile_goal(callback: CallbackQuery, state: FSMContext):
    await state.update_data(goal=callback.data.split(":")[1])
    await callback.message.answer(
        "Есть ли у вас аллергии, непереносимости или ограничения в питании?\n"
        "Например: глютен, лактоза, орехи, вегетарианство.",
        reply_markup=skip_kb(),
    )
    await callback.answer()
    await state.set_state(ProfileSetup.restrictions)


@router.message(ProfileSetup.restrictions)
async def profile_restrictions(message: Message, state: FSMContext):
    await state.update_data(restrictions=message.text.strip())
    await _save_profile(message, state)


@router.callback_query(F.data == "skip")
async def profile_skip(callback: CallbackQuery, state: FSMContext):
    """Универсальная кнопка «Пропустить» для всех необязательных шагов."""
    current = await state.get_state()
    await callback.answer()

    if current == ProfileSetup.age:
        await callback.message.answer("Ваш пол:", reply_markup=gender_kb())
        await state.set_state(ProfileSetup.gender)
    elif current == ProfileSetup.weight:
        await callback.message.answer("Ваш рост (см)?", reply_markup=skip_kb())
        await state.set_state(ProfileSetup.height)
    elif current == ProfileSetup.height:
        await callback.message.answer("Ваша цель:", reply_markup=goal_kb())
        await state.set_state(ProfileSetup.goal)
    elif current == ProfileSetup.restrictions:
        await _save_profile(callback.message, state)


async def _save_profile(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()

    telegram_id = str(message.chat.id)

    fields = {
        k: data[k]
        for k in ("name", "age", "gender", "weight_kg", "height_cm", "goal", "restrictions")
        if k in data and data[k] is not None
    }

    await upsert_user_profile(telegram_id, **fields)

    name = data.get("name", "")
    await message.answer(
        f"Профиль сохранён{', ' + name + '!' if name else '!'} 🎉\n\n"
        "Теперь нутрициолог будет учитывать ваши данные в каждом ответе.\n"
        "Задайте любой вопрос или отправьте фото блюда — /analyze_dish",
    )

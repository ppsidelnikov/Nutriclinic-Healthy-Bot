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

# ─── Описание возможностей (единый источник для /start, /help и LLM) ──────────

CAPABILITIES_HUMAN = """<b>Что я умею:</b>

🥗 <b>Анализ блюда по фото</b>
• /analyze_dish — отправь фото, получишь название, состав, вес и КБЖУ. Без сохранения.

📔 <b>Дневник питания</b>
• /add — записать съеденное в дневник (фото или текст вроде "гречка 200г обед"). Спрошу, к какому приёму пищи отнести.
• /today — сводка за сегодня: прогресс к цели, streak дней, кнопки 🗑 удалить и 🔁 повторить запись.
• /yesterday — сводка за вчера.
• /week — средние ккал и БЖУ за 7 дней, разбивка по дням.
• /saved — твои частые блюда: добавить в дневник одним кликом.
• /undo — удалить последнюю запись.

⚖️ <b>Учёт веса</b>
• /weight 75.4 — записать текущий вес.
• /weight — история и динамика за неделю/месяц.

👤 <b>Профиль и цели</b>
• /profile — посмотреть профиль, /profile_edit — заполнить заново.
• /set_calories &lt;число&gt; — задать суточную цель по калориям. По умолчанию считается автоматически из веса/роста/возраста/цели.

💬 <b>Свободный диалог</b>
Просто задай вопрос — отвечу как нутрициолог, опираясь на проверенные источники (рекомендации ВОЗ, DRI, ISSN). Учитываю твой профиль и сегодняшний дневник питания: например, могу подсказать "какой ужин уложится в оставшиеся 500 ккал".

🛠 <b>Прочее</b>
• /history_clear — очистить историю диалога
• /cancel — отменить текущее действие"""


CAPABILITIES_FOR_LLM = """ВАЖНО: ты — Telegram-бот с конкретным функционалом. Когда пользователь спрашивает "как мне сделать X", "как посчитать калории по фото", "как записать что я съел" — это вопрос про ТВОИ возможности, а не запрос общего совета. Сначала предложи использовать соответствующую команду бота, потом по необходимости добавь короткий контекст.

Команды и возможности:
1. /analyze_dish — пользователь отправляет фото блюда, бот возвращает название, состав, вес и КБЖУ (без сохранения). Используется для разовой оценки.
2. /add — добавить запись в дневник питания. Принимает либо фото, либо текстовое описание ("гречка 200г обед", "яблоко перекус"). После анализа бот спросит, к какому приёму пищи отнести (завтрак/обед/ужин/перекус), и сохранит запись.
3. /today, /yesterday, /week — сводки по дневнику. /today: прогресс к дневной цели по ккал и БЖУ с цветовыми индикаторами (🔵🟢🟡🟠🔴), streak дней подряд, кнопки 🗑 удалить и 🔁 повторить запись. /yesterday: то же за вчерашний день. /week: средние ккал/БЖУ за 7 дней. /saved — авто-сохранёнки: топ-8 самых частых блюд за 14 дней, каждое добавляется одним кликом со средними КБЖУ. /undo — удалить последнюю запись.
4. /weight <число> — записать текущий вес (например /weight 75.4); /weight без аргумента — показать историю и динамику за неделю/месяц. Запись автоматически обновляет вес в профиле.
5. /profile, /profile_edit — управление профилем (имя, возраст, пол, вес, рост, цель: снижение веса / поддержание / набор массы, ограничения).
6. /set_calories <число> — задать целевые калории вручную (например /set_calories 1800); /set_calories auto — пересчитать автоматически из данных профиля по формуле Миффлина-Сан Жеора.
7. /history_clear, /cancel — очистка истории и отмена текущего действия.

Правила ответа:
- На "как посчитать калории по фото" → отвечай: "Отправь фото командой /analyze_dish — я распознаю блюдо и оценю КБЖУ. А если хочешь сразу записать в дневник — используй /add."
- На "как записать что я съел" → отвечай: "Команда /add. Отправь фото или опиши текстом ('гречка 200г обед'), потом выбери приём пищи."
- На "сколько я съел сегодня" → отвечай: "Команда /today покажет полную сводку с прогрессом к цели."
- На "повторить", "то же что вчера", "обычный завтрак" → отвечай: "Команда /saved — там твои частые блюда, можно добавить одним кликом. Или нажми 🔁 под записью в /today."

Запись еды через свободный текст:
- Если пользователь СООБЩАЕТ что съел/выпил/обедал и т.п. — вызывай tool quick_add_food для подготовки записи.
- Примеры триггеров: «съел яблоко», «выпил кофе», «запиши овсянку 200г на завтрак», «обедал курицей с рисом», «у меня был ужин — салат и рыба».
- Не вызывай tool на ВОПРОСАХ («что мне съесть?», «сколько калорий в гречке?») — это запросы информации, не записи.
- ВАЖНО: после quick_add_food бот сам покажет пользователю кнопки выбора приёма пищи и сохранит запись после клика. Ты в своём ответе НЕ должна писать «✓ записал» или «добавил в дневник» — записи ещё нет. Можешь ответить очень кратко («понял», «секунду») или вообще пустой строкой — клавиатура появится отдельным сообщением.
- На "как записать вес" / "сколько я вешу" / "как меняется вес" → отвечай: "Команда /weight 75.4 запишет текущий вес. /weight без аргумента покажет историю и динамику."
- НЕ давай общих советов "взвешивайте продукты, используйте приложения" — пользователь уже использует это приложение, и оно само всё считает.
- Будь лаконичен: 1-3 предложения с указанием команды и кратким примером."""


@router.message(Command("start"))
async def cmd_start(message: Message):
    profile = await get_user_profile(str(message.from_user.id))
    greeting = (f"С возвращением, {profile.name}! 👋"
                if profile and profile.name else
                "Привет! Я — твой персональный нутрициолог 🥗")
    suffix = ""
    if not profile or not profile.name:
        suffix = "\n\n💡 Рекомендую сначала заполнить профиль (/profile) — советы и расчёт калорий будут точнее."
    await message.answer(f"{greeting}\n\n{CAPABILITIES_HUMAN}{suffix}", parse_mode="HTML")


# ─── /help ───────────────────────────────────────────────────────────────────

@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(CAPABILITIES_HUMAN, parse_mode="HTML")


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
            "Хотите обновить данные? Введите /profile_edit\n"
            "Изменить целевые калории: /set_calories &lt;число&gt;",
            parse_mode="HTML",
        )
    else:
        await message.answer(
            "Профиль ещё не заполнен. Давайте исправим! 🙂\n\n"
            "Как вас зовут?"
        )
        await state.set_state(ProfileSetup.name)


@router.message(Command("weight"))
async def cmd_weight(message: Message):
    """Учёт веса: '/weight 75.4' — записать; '/weight' — показать историю."""
    from services.weight_log import add_weight, get_recent, compute_trend, format_history

    parts = (message.text or "").strip().split(maxsplit=1)
    telegram_id = str(message.from_user.id)

    if len(parts) < 2:
        # Без аргументов — показываем историю
        entries = await get_recent(telegram_id, days=30)
        trend = compute_trend(entries)
        await message.answer(format_history(entries, trend), parse_mode="HTML")
        return

    arg = parts[1].strip().replace(",", ".")
    try:
        weight = float(arg)
        if not 30 <= weight <= 300:
            raise ValueError("out of range")
    except ValueError:
        await message.answer(
            "Не понял число. Используй: <code>/weight 75.4</code> "
            "(допустимый диапазон 30–300 кг).",
            parse_mode="HTML",
        )
        return

    await add_weight(telegram_id, weight)

    # Показываем тренд после добавления — пользователь видит прогресс сразу
    entries = await get_recent(telegram_id, days=30)
    trend = compute_trend(entries)

    msg = f"✓ Вес записан: <b>{weight:.1f} кг</b>"
    if trend:
        if trend["delta_7d"] is not None:
            sign = "+" if trend["delta_7d"] >= 0 else ""
            msg += f"\nЗа неделю: {sign}{trend['delta_7d']:.1f} кг"
        if trend["delta_30d"] is not None:
            sign = "+" if trend["delta_30d"] >= 0 else ""
            msg += f"\nЗа месяц: {sign}{trend['delta_30d']:.1f} кг"
    await message.answer(msg, parse_mode="HTML")


@router.message(Command("set_calories"))
async def cmd_set_calories(message: Message):
    """Ручной override целевых калорий: /set_calories 1800."""
    parts = (message.text or "").strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "Использование: <code>/set_calories &lt;число&gt;</code>\n"
            "Например: <code>/set_calories 1800</code>\n\n"
            "Чтобы вернуть авто-расчёт по профилю — <code>/set_calories auto</code>",
            parse_mode="HTML",
        )
        return

    arg = parts[1].strip().lower()
    telegram_id = str(message.from_user.id)

    if arg == "auto":
        from services.user_profile import compute_daily_calories_target
        profile = await get_user_profile(telegram_id)
        target = compute_daily_calories_target(profile)
        if not target:
            await message.answer(
                "Не хватает данных в профиле для авто-расчёта "
                "(нужны вес, рост, возраст, пол, цель). Заполни /profile_edit."
            )
            return
        await upsert_user_profile(telegram_id, daily_calories_target=target)
        await message.answer(
            f"Целевые калории пересчитаны автоматически: <b>{target} ккал/день</b>.",
            parse_mode="HTML",
        )
        return

    try:
        target = int(arg)
        if not 800 <= target <= 6000:
            raise ValueError("out of range")
    except ValueError:
        await message.answer(
            "Не понял число. Используй: <code>/set_calories 1800</code> "
            "(допустимый диапазон 800–6000 ккал).",
            parse_mode="HTML",
        )
        return

    await upsert_user_profile(telegram_id, daily_calories_target=target)
    await message.answer(
        f"✓ Цель установлена: <b>{target} ккал/день</b>.\n"
        "Теперь /today будет показывать прогресс к этой цели.",
        parse_mode="HTML",
    )


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

    # Авто-расчёт целевых калорий (если хватает данных)
    from services.user_profile import compute_daily_calories_target
    saved = await get_user_profile(telegram_id)
    target = compute_daily_calories_target(saved)
    if target:
        await upsert_user_profile(telegram_id, daily_calories_target=target)

    name = data.get("name", "")
    extra = ""
    if target:
        extra = (
            f"\n\nЦелевая калорийность рассчитана автоматически: "
            f"<b>{target} ккал/день</b>.\n"
            f"Изменить вручную: /set_calories &lt;число&gt;"
        )
    await message.answer(
        f"Профиль сохранён{', ' + name + '!' if name else '!'} 🎉\n\n"
        "Теперь нутрициолог будет учитывать ваши данные в каждом ответе.\n"
        "Задайте любой вопрос или отправьте фото блюда — /analyze_dish"
        + extra,
        parse_mode="HTML",
    )

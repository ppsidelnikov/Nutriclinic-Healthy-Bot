import logging
import os

from bot_setup import dp, bot
from handlers.base_handlers import router as base_router
from handlers.food_calories_count_handlers import router as gpt_router
from handlers.food_diary_handlers import router as diary_router
from middlewares import LoggingMiddleware
from services.rag import warmup as rag_warmup
from aiogram.types import BotCommand

logger = logging.getLogger(__name__)


async def on_startup(bot_):
    # set_my_commands может упасть если Telegram API недоступен (например,
    # через прокси из ограниченной сети). Не валим контейнер в этом случае —
    # сервисы всё равно нужно прогреть для нагрузочных тестов.
    try:
        await bot_.set_my_commands([
            BotCommand(command="analyze_dish",   description="Анализ блюда по фото (КБЖУ)"),
            BotCommand(command="add",            description="Дневник: записать еду"),
            BotCommand(command="today",          description="Дневник: что съел сегодня"),
            BotCommand(command="yesterday",      description="Дневник: что съел вчера"),
            BotCommand(command="week",           description="Дневник: сводка за неделю"),
            BotCommand(command="saved",          description="Сохранёнки: частые блюда"),
            BotCommand(command="undo",           description="Удалить последнюю запись"),
            BotCommand(command="weight",         description="Записать вес и посмотреть динамику"),
            BotCommand(command="profile",        description="Мой профиль"),
            BotCommand(command="set_calories",   description="Цель по калориям на день"),
            BotCommand(command="history_clear",  description="Очистить историю диалога"),
            BotCommand(command="cancel",         description="Отменить текущее действие"),
        ])
    except Exception as e:
        logger.warning("set_my_commands упал (Telegram недоступен?): %s", e)

    # Прогреваем RAG: загружаем BM25-индекс и cross-encoder, чтобы первый
    # пользовательский запрос не страдал от холодного старта (~3-5 сек).
    logger.info("Прогрев RAG-сервиса …")
    try:
        await rag_warmup()
        logger.info("RAG прогрет")
    except Exception as e:
        logger.exception("RAG warmup упал, бот всё равно стартует: %s", e)


async def main():
    # base_router первым — чтобы /start, /profile, /help перехватывались до catch-all
    # diary_router до gpt_router — чтобы /today, /add, callback'и обрабатывались первыми
    dp.include_routers(base_router, diary_router, gpt_router)
    dp.message.middleware(LoggingMiddleware())
    dp.callback_query.middleware(LoggingMiddleware())
    await on_startup(bot)
    if os.getenv("ENVIRONMENT") == "production":
        # В проде — обычное поведение: если polling упал, контейнер падает,
        # Docker рестартует (это правильно — Telegram должен быть доступен).
        await dp.start_polling(bot)
    else:
        # В dev/test — держим контейнер живым даже если Telegram недоступен,
        # чтобы можно было запускать нагрузочные тесты через docker exec.
        try:
            await dp.start_polling(bot)
        except Exception as e:
            logger.exception("Polling упал, держим контейнер живым (dev): %s", e)
            import asyncio as _a
            while True:
                await _a.sleep(3600)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

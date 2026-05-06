import logging

from bot_setup import dp, bot
from handlers.base_handlers import router as base_router
from handlers.food_calories_count_handlers import router as gpt_router
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
            BotCommand(command="profile",        description="Мой профиль"),
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
    dp.include_routers(base_router, gpt_router)
    dp.message.middleware(LoggingMiddleware())
    dp.callback_query.middleware(LoggingMiddleware())
    await on_startup(bot)
    try:
        await dp.start_polling(bot)
    except Exception as e:
        # Telegram polling может падать на ограниченных сетях — для нагрузочных
        # тестов это не блокер: сервисы доступны через docker exec.
        logger.exception("Polling упал, держим контейнер живым для нагрузочных тестов: %s", e)
        import asyncio as _a
        while True:
            await _a.sleep(3600)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

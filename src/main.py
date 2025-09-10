from bot_setup import dp, bot
from handlers.food_calories_count_handlers import router as gpt_router
from middlewares import LoggingMiddleware
from aiogram.types import BotCommand

async def on_startup(bot_):
    # Кнопки меню «/»
    await bot_.set_my_commands([
        BotCommand(command="analyze_dish", description="Оценить блюдо по фото"),
        BotCommand(command="cancel", description="Отменить текущую операцию"),
    ])

async def main():
    dp.include_routers(gpt_router) ### сюда список хендлеров
    # Логируем входящие сообщения и callback-и через специализированные middleware уровни
    dp.message.middleware(LoggingMiddleware())
    dp.callback_query.middleware(LoggingMiddleware())
    await on_startup(bot)
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
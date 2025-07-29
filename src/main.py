from bot_setup import dp, bot
from handlers.gpt_answer_handlers import router as gpt_router
from middlewares import LoggingMiddleware

async def main():
    dp.include_routers(gpt_router) ### сюда список хендлеров
    dp.update.middleware(LoggingMiddleware())
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
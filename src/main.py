from bot_setup import dp, bot
#### место для импорта хендлеров
from middlewares import LoggingMiddleware

async def main():
    dp.include_routers() ### сюда список хендлеров
    dp.update.middleware(LoggingMiddleware())
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
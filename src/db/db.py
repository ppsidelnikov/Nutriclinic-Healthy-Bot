import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from config.config import config

DB_USER = config.DB_USER
DB_PASSWORD = config.DB_PASSWORD
DB_HOST = config.DB_HOST 
DB_PORT = config.DB_PORT 
DB_NAME = config.DB_NAME

DB_URL = (
    f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}"
    f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

# Движок и сессии. SQL-эхо отключено по умолчанию — забивает консоль
# и нагрузочные тесты. Включается явно через DB_ECHO=1 для отладки.
_echo = os.getenv("DB_ECHO", "0") in ("1", "true", "True")
engine = create_async_engine(DB_URL, echo=_echo, future=True)
AsyncSessionLocal = sessionmaker(
    bind=engine, expire_on_commit=False, class_=AsyncSession
)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from shared.config import DB_URL

engine = create_async_engine(DB_URL, echo=False)
AsyncSessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async def get_all_chunks() -> list[dict]:
    """Загружает все чанки из БД: [{id, text, source}]."""
    sql = text("SELECT id, text, source FROM knowledge_chunks ORDER BY id")
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(sql)).fetchall()
    return [{"id": r[0], "text": r[1], "source": r[2]} for r in rows]


async def check_connection() -> int:
    """Возвращает количество чанков в БД или бросает исключение."""
    sql = text("SELECT COUNT(*) FROM knowledge_chunks")
    async with AsyncSessionLocal() as session:
        result = await session.execute(sql)
        return result.scalar()

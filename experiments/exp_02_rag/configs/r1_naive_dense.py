"""R1 — наивный плотный поиск через pgvector (cosine similarity)."""

from sqlalchemy import text
from shared.db import AsyncSessionLocal
from shared.embeddings import get_embedding

CONFIG_NAME = "R1"


async def retrieve(query: str, top_k: int = 3) -> list[dict]:
    """
    Возвращает top_k чанков по косинусному сходству эмбеддинга запроса.
    Каждый элемент: {text, source, score, rank}.
    """
    embedding = await get_embedding(query)
    emb_str = "[" + ",".join(str(x) for x in embedding) + "]"

    sql = text("""
        SELECT text, source,
               1 - (embedding <=> CAST(:emb AS vector)) AS score
        FROM knowledge_chunks
        ORDER BY embedding <=> CAST(:emb AS vector)
        LIMIT :k
    """)

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(sql, {"emb": emb_str, "k": top_k})).fetchall()

    return [
        {"text": r[0], "source": r[1], "score": float(r[2]), "rank": i + 1}
        for i, r in enumerate(rows)
    ]

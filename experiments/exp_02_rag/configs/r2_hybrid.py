"""
R2 — гибридный поиск: dense (pgvector) + BM25, объединение через RRF.

Алгоритм:
  1. Dense: top-N кандидатов из pgvector
  2. BM25:  top-N кандидатов из in-memory индекса по всем чанкам
  3. RRF:   reciprocal rank fusion с k=60
  4. Вернуть top_k по RRF-score
"""

from rank_bm25 import BM25Okapi
from sqlalchemy import text
from shared.db import AsyncSessionLocal, get_all_chunks
from shared.embeddings import get_embedding

CONFIG_NAME = "R2"
RRF_K = 60          # стандартный параметр RRF
N_CANDIDATES = 10   # сколько кандидатов берём из каждого источника


def _tokenize(text: str) -> list[str]:
    return text.lower().split()


def _rrf_fusion(
    dense_ids: list[int],
    bm25_ids: list[int],
    all_chunks: list[dict],
    k: int = RRF_K,
) -> list[dict]:
    """Объединяет два ранжированных списка ID через RRF."""
    scores: dict[int, float] = {}
    for rank, cid in enumerate(dense_ids, start=1):
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    for rank, cid in enumerate(bm25_ids, start=1):
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)

    chunk_by_id = {c["id"]: c for c in all_chunks}
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    return [
        {**chunk_by_id[cid], "score": score, "rank": i + 1}
        for i, (cid, score) in enumerate(ranked)
        if cid in chunk_by_id
    ]


async def retrieve(query: str, top_k: int = 3) -> list[dict]:
    # 1. Загружаем все чанки (один раз per-call; в продакшене кэшировать)
    all_chunks = await get_all_chunks()
    corpus = [_tokenize(c["text"]) for c in all_chunks]
    bm25 = BM25Okapi(corpus)

    # 2. Dense search
    embedding = await get_embedding(query)
    emb_str = "[" + ",".join(str(x) for x in embedding) + "]"
    sql = text("""
        SELECT id FROM knowledge_chunks
        ORDER BY embedding <=> CAST(:emb AS vector)
        LIMIT :n
    """)
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(sql, {"emb": emb_str, "n": N_CANDIDATES})).fetchall()
    dense_ids = [r[0] for r in rows]

    # 3. BM25 search
    query_tokens = _tokenize(query)
    bm25_scores = bm25.get_scores(query_tokens)
    bm25_ranked = sorted(
        range(len(all_chunks)), key=lambda i: -bm25_scores[i]
    )[:N_CANDIDATES]
    bm25_ids = [all_chunks[i]["id"] for i in bm25_ranked]

    # 4. RRF + top_k
    fused = _rrf_fusion(dense_ids, bm25_ids, all_chunks)
    return fused[:top_k]

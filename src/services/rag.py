"""
RAG-сервис: продакшен-конфигурация R6 из §3.2 диссертации.

Пайплайн:
  1. Перевод запроса RU → EN (gpt-4o-mini, температура 0)
  2. Гибридный поиск по EN-запросу:
       - Dense: pgvector cosine, top-N кандидатов
       - BM25:  in-memory индекс по всем чанкам, top-N кандидатов
  3. Reciprocal Rank Fusion (k=60) — слияние двух списков
  4. Cross-encoder rerank (mmarco-mMiniLMv2-L12-H384-v1) на топ-10 кандидатов
  5. Релевантностный гейтинг: если max(ce_score) < CE_THRESHOLD,
     RAG-контекст не возвращается — ассистент отвечает без опоры на источники

Публичный API (совместимый с предыдущей реализацией):
  get_embedding(text)              → list[float]
  search_knowledge(query, top_k=3) → list[str]   — топ-k чанков (или [] если gating)
  format_rag_context(chunks)       → str

Эталонный эксперимент: experiments/exp_02_rag/configs/r6_translated_rerank_gated.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import List, Optional

from openai import AsyncOpenAI
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder
from sqlalchemy import text

sys.path.append(str(Path(__file__).parent.parent))

from config.config import config
from db.db import AsyncSessionLocal

logger = logging.getLogger(__name__)

# === Константы пайплайна (соответствуют экспериментальной R6 из §3.2) ===
EMBEDDING_MODEL    = "text-embedding-3-small"
TRANSLATE_MODEL    = "gpt-4o-mini"
RERANKER_MODEL     = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
RRF_K              = 60          # параметр Reciprocal Rank Fusion
N_CANDIDATES       = 10          # топ-N из каждой ветви поиска
N_RERANK           = 10           # сколько кандидатов передаём в кросс-энкодер
CE_THRESHOLD       = -3.0        # порог гейтинга (калиброван на in-scope vs out-of-scope, §3.2)

TRANSLATE_SYSTEM_PROMPT = (
    "Translate the following nutrition-related question from Russian to English. "
    "Output only the translation, nothing else."
)


# ──────────────────────────────────────────────────────────────────────────────
# Внутренние state-объекты (ленивая инициализация, чтобы не платить на старте)
# ──────────────────────────────────────────────────────────────────────────────
_openai: Optional[AsyncOpenAI] = None
_cross_encoder: Optional[CrossEncoder] = None
_bm25: Optional[BM25Okapi] = None
_all_chunks: Optional[List[dict]] = None  # [{id, text, source}, ...]


def _get_openai() -> AsyncOpenAI:
    global _openai
    if _openai is None:
        _openai = AsyncOpenAI(
            api_key=config.PROXY_API_TEST_KEY,
            base_url=config.PROXY_API_BASE_URL,
        )
    return _openai


def _get_cross_encoder() -> CrossEncoder:
    """Загружает кросс-энкодер один раз. Первая загрузка ~2-3 секунды (CPU)."""
    global _cross_encoder
    if _cross_encoder is None:
        logger.info("Загрузка cross-encoder %s …", RERANKER_MODEL)
        _cross_encoder = CrossEncoder(RERANKER_MODEL)
        logger.info("Cross-encoder загружен")
    return _cross_encoder


def _tokenize(s: str) -> List[str]:
    """Токенизация для BM25. Простой lowercase.split — для англоязычного корпуса достаточно."""
    return s.lower().split()


async def _load_all_chunks() -> List[dict]:
    """Загружает все чанки из knowledge_chunks один раз и кэширует.

    Для корпуса в 2-3 тыс. чанков это десятки МБ — приемлемо для in-memory кэша.
    При росте корпуса (>50k чанков) нужно перенести BM25 в выделенный сервис.
    """
    global _all_chunks, _bm25
    if _all_chunks is not None:
        return _all_chunks

    sql = text("SELECT id, text, source FROM knowledge_chunks ORDER BY id")
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(sql)).fetchall()

    _all_chunks = [{"id": r[0], "text": r[1], "source": r[2]} for r in rows]
    corpus = [_tokenize(c["text"]) for c in _all_chunks]
    _bm25 = BM25Okapi(corpus)
    logger.info("BM25-индекс построен: %d чанков", len(_all_chunks))
    return _all_chunks


async def warmup() -> None:
    """Прогревает кэши на старте бота: BM25-индекс и cross-encoder.
    Без warmup'а первый пользовательский запрос будет на 3-5 секунд медленнее.
    """
    await _load_all_chunks()
    _get_cross_encoder()


# ──────────────────────────────────────────────────────────────────────────────
# Этапы пайплайна
# ──────────────────────────────────────────────────────────────────────────────
async def get_embedding(text_input: str) -> List[float]:
    """Векторизует текст через ProxyAPI (text-embedding-3-small, 1536D)."""
    response = await _get_openai().embeddings.create(
        model=EMBEDDING_MODEL,
        input=text_input.replace("\n", " "),
    )
    return response.data[0].embedding


async def _translate_to_english(query: str) -> str:
    """Перевод запроса RU → EN через gpt-4o-mini. Один LLM-вызов, ~500мс."""
    response = await _get_openai().chat.completions.create(
        model=TRANSLATE_MODEL,
        temperature=0,
        max_tokens=200,
        messages=[
            {"role": "system", "content": TRANSLATE_SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ],
    )
    return response.choices[0].message.content.strip()


async def _dense_search(en_query: str, n: int) -> List[int]:
    """Плотный поиск через pgvector. Возвращает список chunk_id в порядке близости."""
    embedding = await get_embedding(en_query)
    emb_str = "[" + ",".join(str(x) for x in embedding) + "]"
    sql = text("""
        SELECT id FROM knowledge_chunks
        ORDER BY embedding <=> CAST(:emb AS vector)
        LIMIT :n
    """)
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(sql, {"emb": emb_str, "n": n})).fetchall()
    return [r[0] for r in rows]


def _bm25_search(en_query: str, n: int) -> List[int]:
    """BM25-поиск по in-memory индексу. Возвращает chunk_id в порядке релевантности."""
    assert _bm25 is not None and _all_chunks is not None, "Вызови warmup() на старте"
    scores = _bm25.get_scores(_tokenize(en_query))
    top_idx = sorted(range(len(_all_chunks)), key=lambda i: -scores[i])[:n]
    return [_all_chunks[i]["id"] for i in top_idx]


def _rrf_fusion(dense_ids: List[int], bm25_ids: List[int]) -> List[dict]:
    """Reciprocal Rank Fusion — объединение двух ранжированных списков."""
    assert _all_chunks is not None
    chunk_by_id = {c["id"]: c for c in _all_chunks}
    scores: dict[int, float] = {}
    for rank, cid in enumerate(dense_ids, start=1):
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (RRF_K + rank)
    for rank, cid in enumerate(bm25_ids, start=1):
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (RRF_K + rank)
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    return [chunk_by_id[cid] for cid, _ in ranked if cid in chunk_by_id]


def _rerank(en_query: str, candidates: List[dict], top_k: int) -> List[dict]:
    """Cross-encoder rerank на одноязычных EN-парах (запрос ↔ чанк).

    Возвращает топ-k с приклеенным ce_score для последующего гейтинга.
    """
    if not candidates:
        return []
    ce = _get_cross_encoder()
    pairs = [(en_query, c["text"]) for c in candidates]
    scores = ce.predict(pairs)
    reranked = sorted(zip(candidates, scores), key=lambda x: -float(x[1]))
    return [{**chunk, "ce_score": float(score)} for chunk, score in reranked[:top_k]]


# ──────────────────────────────────────────────────────────────────────────────
# Публичный API
# ──────────────────────────────────────────────────────────────────────────────
async def search_knowledge(query: str, top_k: int = 3) -> List[str]:
    """Полный пайплайн R6: translate → hybrid → rerank → gate.

    Возвращает топ-k текстов чанков, либо пустой список если максимальный
    ce_score ниже порога θ=-3 (gating: запрос off-topic или корпусный пробел).
    """
    if not query or not query.strip():
        return []

    # Гарантируем что in-memory индексы построены (no-op после warmup)
    await _load_all_chunks()

    try:
        en_query = await _translate_to_english(query)
    except Exception as e:
        logger.warning("Перевод RU→EN упал: %s. Fallback на оригинальный запрос.", e)
        en_query = query

    # Параллельно — dense и BM25 (BM25 синхронный, но быстрый)
    dense_ids = await _dense_search(en_query, N_CANDIDATES)
    bm25_ids = _bm25_search(en_query, N_CANDIDATES)

    candidates = _rrf_fusion(dense_ids, bm25_ids)[:N_RERANK]
    reranked = _rerank(en_query, candidates, top_k=top_k)

    if not reranked:
        return []

    # Gating: отключается через env-переменную RAG_DISABLE_GATING=1
    # (используется в нагрузочном эксперименте L2 §3.3 для замера эффекта).
    import os as _os
    if _os.getenv("RAG_DISABLE_GATING") != "1":
        top_score = reranked[0]["ce_score"]
        if top_score < CE_THRESHOLD:
            logger.info("RAG gating: top ce_score %.3f < %.1f, контекст не возвращён",
                        top_score, CE_THRESHOLD)
            return []

    return [c["text"] for c in reranked]


def format_rag_context(chunks: List[str]) -> str:
    """Форматирует чанки в текстовый блок для системного промпта.

    При пустом списке возвращает пустую строку — генеративная LLM в этом случае
    отвечает без RAG-контекста (системный промпт инструктирует честно сообщать
    об отсутствии данных).
    """
    if not chunks:
        return ""
    joined = "\n\n---\n\n".join(chunks)
    return f"Релевантные материалы из базы знаний по нутрициологии:\n\n{joined}"

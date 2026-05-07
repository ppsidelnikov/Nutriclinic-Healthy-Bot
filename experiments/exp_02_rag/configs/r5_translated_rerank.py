"""
R5 — R4 (перевод запроса + гибридный поиск) + cross-encoder reranking.

Алгоритм:
  1. Перевод запроса RU→EN
  2. R2-retrieval на EN-запросе → top-N_RERANK кандидатов
  3. Cross-encoder переоценивает (EN-query, EN-chunk)
  4. Top-k по cross-encoder score
"""

from __future__ import annotations
from typing import Optional
from sentence_transformers import CrossEncoder
from configs.r2_hybrid import retrieve as r2_retrieve
from configs.r4_hybrid_translated import translate_to_english

CONFIG_NAME = "R5"
N_RERANK = 10

_CROSS_ENCODER_MODEL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
_cross_encoder: Optional[CrossEncoder] = None


def _get_cross_encoder() -> CrossEncoder:
    global _cross_encoder
    if _cross_encoder is None:
        _cross_encoder = CrossEncoder(_CROSS_ENCODER_MODEL)
    return _cross_encoder


async def retrieve(query: str, top_k: int = 3) -> list[dict]:
    en_query = await translate_to_english(query)
    candidates = await r2_retrieve(en_query, top_k=N_RERANK)
    if not candidates:
        return []

    ce = _get_cross_encoder()
    pairs = [(en_query, c["text"]) for c in candidates]
    ce_scores = ce.predict(pairs)

    reranked = sorted(zip(candidates, ce_scores), key=lambda x: -float(x[1]))
    return [
        {**chunk, "ce_score": float(score), "rank": i + 1, "translated_query": en_query}
        for i, (chunk, score) in enumerate(reranked[:top_k])
    ]

"""
R3 — гибридный поиск R2 + cross-encoder reranking.

Алгоритм:
  1. R2 retrieval: получаем top-N_RERANK кандидатов
  2. Cross-encoder: переоцениваем каждую пару (query, chunk)
  3. Сортируем по score cross-encoder → top_k
"""

from __future__ import annotations
from typing import Optional
from sentence_transformers import CrossEncoder
from configs.r2_hybrid import retrieve as r2_retrieve

CONFIG_NAME = "R3"
N_RERANK = 10  # сколько кандидатов передаём в cross-encoder

# Мультиязычная модель: поддерживает русские запросы + английские документы
_CROSS_ENCODER_MODEL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
_cross_encoder: Optional[CrossEncoder] = None


def _get_cross_encoder() -> CrossEncoder:
    global _cross_encoder
    if _cross_encoder is None:
        _cross_encoder = CrossEncoder(_CROSS_ENCODER_MODEL)
    return _cross_encoder


async def retrieve(query: str, top_k: int = 3) -> list[dict]:
    # 1. R2-кандидаты (берём больше, чтобы было что ранжировать)
    candidates = await r2_retrieve(query, top_k=N_RERANK)
    if not candidates:
        return []

    # 2. Cross-encoder scoring
    ce = _get_cross_encoder()
    pairs = [(query, c["text"]) for c in candidates]
    ce_scores = ce.predict(pairs)

    # 3. Rerank и вернуть top_k
    reranked = sorted(
        zip(candidates, ce_scores),
        key=lambda x: -float(x[1]),
    )
    return [
        {**chunk, "ce_score": float(score), "rank": i + 1}
        for i, (chunk, score) in enumerate(reranked[:top_k])
    ]

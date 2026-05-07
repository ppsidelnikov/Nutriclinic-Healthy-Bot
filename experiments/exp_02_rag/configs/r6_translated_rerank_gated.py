"""
R6 — R5 (перевод + гибрид + reranking) с релевантностным гейтингом.

Если максимальный ce_score топ-1 кандидата ниже эмпирически калиброванного
порога θ = −3, RAG-контекст не передаётся — модель отвечает без опоры на
источники (системный промпт инструктирует честно сообщить об отсутствии данных).

Калибровка порога: см. §3.2, эксперимент с ce_score-распределениями
in-scope (n=63) и out-of-scope (n=20) запросов.
"""

from __future__ import annotations
from configs.r5_translated_rerank import retrieve as r5_retrieve

CONFIG_NAME = "R6"
CE_THRESHOLD = -3.0


async def retrieve(query: str, top_k: int = 3) -> list[dict]:
    chunks = await r5_retrieve(query, top_k=top_k)
    if not chunks:
        return []
    top_score = chunks[0].get("ce_score", float("-inf"))
    if top_score < CE_THRESHOLD:
        return []  # gated: модуль поиска признал результат нерелевантным
    return chunks

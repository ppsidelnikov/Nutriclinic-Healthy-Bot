"""
R4 — гибридный поиск R2 с предварительным переводом запроса RU→EN.

Алгоритм:
  1. Перевод запроса с русского на английский (gpt-4o-mini)
  2. R2 retrieval на переведённом запросе (dense + BM25 + RRF)
  3. Ответ генерируется на оригинальном русском запросе
"""

from __future__ import annotations
from typing import Optional
from openai import AsyncOpenAI
from configs.r2_hybrid import retrieve as r2_retrieve
from shared.config import PROXY_API_KEY, PROXY_API_BASE_URL, ANSWER_MODEL

CONFIG_NAME = "R4"

_client: Optional[AsyncOpenAI] = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=PROXY_API_KEY, base_url=PROXY_API_BASE_URL)
    return _client


async def translate_to_english(query: str) -> str:
    response = await _get_client().chat.completions.create(
        model=ANSWER_MODEL,
        temperature=0,
        max_tokens=200,
        messages=[
            {
                "role": "system",
                "content": "Translate the following nutrition-related question from Russian to English. Output only the translation, nothing else.",
            },
            {"role": "user", "content": query},
        ],
    )
    return response.choices[0].message.content.strip()


async def retrieve(query: str, top_k: int = 3) -> list[dict]:
    en_query = await translate_to_english(query)
    chunks = await r2_retrieve(en_query, top_k=top_k)
    return [{**c, "translated_query": en_query} for c in chunks]

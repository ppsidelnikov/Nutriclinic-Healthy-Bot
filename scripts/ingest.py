"""
Загрузчик документов в базу знаний (RAG).

Использование:
  python scripts/ingest.py                     # все PDF из docs/
  python scripts/ingest.py docs/my_book.pdf    # конкретный файл
  python scripts/ingest.py --clear             # очистить базу и загрузить заново

Процесс:
  PDF → извлечение текста → разбивка на чанки (~500 токенов) →
  эмбеддинг каждого чанка (ProxyAPI) → сохранение в PostgreSQL knowledge_chunks
"""

import asyncio
import sys
import os
import time
from pathlib import Path

# Добавляем src/ в путь, чтобы импортировать конфиг и сервисы
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import tiktoken
from pypdf import PdfReader
from sqlalchemy import text, delete
from db.db import AsyncSessionLocal
from db.models import KnowledgeChunk
from services.rag import get_embedding

# ─── Настройки чанкинга ───────────────────────────────────────────────────────

CHUNK_TOKENS    = 500    # целевой размер чанка в токенах
OVERLAP_TOKENS  = 50     # перекрытие между соседними чанками (контекст на стыке)
EMBED_BATCH     = 20     # сколько чанков отправлять за один API-запрос
RATE_LIMIT_WAIT = 0.3    # пауза между батчами (сек) — защита от rate limit

enc = tiktoken.get_encoding("cl100k_base")


# ─── Извлечение текста из PDF ─────────────────────────────────────────────────

def extract_text(pdf_path: Path) -> str:
    reader = PdfReader(str(pdf_path))
    pages = []
    for page in reader.pages:
        t = page.extract_text()
        if t:
            pages.append(t.strip())
    return "\n\n".join(pages)


# ─── Разбивка на чанки ───────────────────────────────────────────────────────

def split_into_chunks(text: str) -> list[str]:
    tokens = enc.encode(text)
    chunks = []
    step = CHUNK_TOKENS - OVERLAP_TOKENS
    for start in range(0, len(tokens), step):
        chunk_tokens = tokens[start : start + CHUNK_TOKENS]
        chunks.append(enc.decode(chunk_tokens))
        if start + CHUNK_TOKENS >= len(tokens):
            break
    return chunks


# ─── Сохранение в Postgres ───────────────────────────────────────────────────

async def save_chunks(source: str, chunks: list[str], embeddings: list[list[float]]):
    async with AsyncSessionLocal() as session:
        # Удаляем старые чанки из этого источника (idempotent re-ingest)
        await session.execute(
            delete(KnowledgeChunk).where(KnowledgeChunk.source == source)
        )
        for idx, (chunk_text, emb) in enumerate(zip(chunks, embeddings)):
            session.add(KnowledgeChunk(
                source=source,
                chunk_index=idx,
                text=chunk_text,
                embedding=emb,
            ))
        await session.commit()


# ─── Основной процесс ────────────────────────────────────────────────────────

async def ingest_file(pdf_path: Path):
    print(f"\n📄 {pdf_path.name}")

    print("  Извлекаю текст...")
    raw_text = extract_text(pdf_path)
    if not raw_text.strip():
        print("  ⚠️  Текст не извлечён (возможно, скан). Пропускаю.")
        return

    chunks = split_into_chunks(raw_text)
    print(f"  Чанков: {len(chunks)} (~{CHUNK_TOKENS} токенов каждый)")

    print("  Векторизую...")
    embeddings = []
    for i in range(0, len(chunks), EMBED_BATCH):
        batch = chunks[i : i + EMBED_BATCH]
        batch_embs = []
        for chunk in batch:
            emb = await get_embedding(chunk)
            batch_embs.append(emb)
        embeddings.extend(batch_embs)
        print(f"  {min(i + EMBED_BATCH, len(chunks))}/{len(chunks)} чанков")
        if i + EMBED_BATCH < len(chunks):
            time.sleep(RATE_LIMIT_WAIT)

    print("  Сохраняю в Postgres...")
    await save_chunks(pdf_path.name, chunks, embeddings)
    print(f"  ✅ {pdf_path.name} — {len(chunks)} чанков загружено")


async def clear_db():
    async with AsyncSessionLocal() as session:
        await session.execute(delete(KnowledgeChunk))
        await session.commit()
    print("🗑️  База знаний очищена")


async def show_stats():
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT source, COUNT(*) FROM knowledge_chunks GROUP BY source ORDER BY source")
        )
        rows = result.fetchall()
    if not rows:
        print("\nБаза знаний пуста.")
        return
    print("\n📊 Текущее состояние базы знаний:")
    for source, count in rows:
        print(f"  {source}: {count} чанков")


async def main():
    args = sys.argv[1:]
    docs_dir = ROOT / "docs"

    if "--clear" in args:
        await clear_db()
        args = [a for a in args if a != "--clear"]

    if not args:
        # Загружаем все PDF из docs/
        pdf_files = sorted(docs_dir.glob("*.pdf"))
        if not pdf_files:
            print(f"⚠️  В папке {docs_dir} нет PDF-файлов.")
            print("    Положи документы в docs/ и запусти снова.")
            return
    else:
        pdf_files = [Path(a) for a in args]

    for pdf_path in pdf_files:
        if not pdf_path.exists():
            print(f"⚠️  Файл не найден: {pdf_path}")
            continue
        await ingest_file(pdf_path)

    await show_stats()


if __name__ == "__main__":
    asyncio.run(main())

"""
Проверяет готовность среды перед запуском эксперимента:
  - подключение к PostgreSQL
  - количество чанков в knowledge_chunks
  - ProxyAPI (тестовый embedding-запрос)
  - cross-encoder (загрузка модели)

Запуск: python check_setup.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


async def check_db():
    from shared.db import check_connection
    n = await check_connection()
    print(f"  ✅ PostgreSQL: {n} чанков в knowledge_chunks")
    if n == 0:
        print("  ⚠️  База пуста — запустите scripts/ingest.py в папке бота")
    return n > 0


async def check_embedding():
    from shared.embeddings import get_embedding
    emb = await get_embedding("тест")
    assert len(emb) == 1536
    print(f"  ✅ ProxyAPI embeddings: размерность {len(emb)}")
    return True


async def check_llm():
    from shared.llm import generate_answer
    answer, p, c = await generate_answer("Сколько белка нужно в день?", [])
    print(f"  ✅ ProxyAPI LLM: ответ получен ({p}+{c} токенов)")
    return True


def check_cross_encoder():
    from sentence_transformers import CrossEncoder
    ce = CrossEncoder("cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")
    score = ce.predict([("test query", "test document")])
    print(f"  ✅ Cross-encoder: модель загружена, score={float(score[0]):.3f}")
    return True


async def main():
    print("Проверяю готовность эксперимента...\n")
    results = {}

    print("1. PostgreSQL:")
    try:
        results["db"] = await check_db()
    except Exception as e:
        print(f"  ❌ {e}")
        results["db"] = False

    print("\n2. ProxyAPI — embeddings:")
    try:
        results["emb"] = await check_embedding()
    except Exception as e:
        print(f"  ❌ {e}")
        results["emb"] = False

    print("\n3. ProxyAPI — LLM:")
    try:
        results["llm"] = await check_llm()
    except Exception as e:
        print(f"  ❌ {e}")
        results["llm"] = False

    print("\n4. Cross-encoder (sentence-transformers):")
    try:
        results["ce"] = check_cross_encoder()
    except Exception as e:
        print(f"  ❌ {e}")
        results["ce"] = False

    print()
    all_ok = all(results.values())
    if all_ok:
        print("✅ Всё готово. Запускайте: python run.py --dry-run")
    else:
        failed = [k for k, v in results.items() if not v]
        print(f"❌ Проблемы: {', '.join(failed)}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

"""
Запускает три RAG-конфигурации на наборе QA-пар и сохраняет результаты.

Использование:
  python run.py                     # все три конфига
  python run.py --config R1         # только R1
  python run.py --config R1 R2      # R1 и R2
  python run.py --dry-run           # 5 вопросов для проверки
"""

import asyncio
import json
import sys
import time
import argparse
from pathlib import Path
from tqdm import tqdm

# Добавляем папку experiments в sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.db import check_connection
from shared.llm import generate_answer
from configs import (
    r1_naive_dense, r2_hybrid, r3_hybrid_rerank,
    r4_hybrid_translated, r5_translated_rerank, r6_translated_rerank_gated,
)

QA_PATH     = Path(__file__).parent / "qa_set" / "qa_pairs.jsonl"
RESULTS_DIR = Path(__file__).parent / "results"

CONFIGS = {
    "R1": r1_naive_dense,
    "R2": r2_hybrid,
    "R3": r3_hybrid_rerank,
    "R4": r4_hybrid_translated,
    "R5": r5_translated_rerank,
    "R6": r6_translated_rerank_gated,
}


def load_qa_pairs(path: Path) -> list[dict]:
    pairs = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                pairs.append(json.loads(line))
    return pairs


async def run_single(config_module, qa_pairs: list[dict]) -> list[dict]:
    name = config_module.CONFIG_NAME
    results = []

    pbar = tqdm(qa_pairs, desc=f"[{name}]", unit="q", ncols=90, colour="cyan")
    for pair in pbar:
        question = pair["question"]
        pbar.set_postfix_str(question[:45] + "…")

        t0 = time.perf_counter()
        try:
            chunks = await config_module.retrieve(question, top_k=3)
            chunk_texts = [c["text"] for c in chunks]
            chunk_sources = [c["source"] for c in chunks]

            answer, p_tok, c_tok = await generate_answer(question, chunk_texts)
            latency_ms = (time.perf_counter() - t0) * 1000

            results.append({
                "config":        name,
                "question":      question,
                "ground_truth":  pair["ground_truth"],
                "reference_pdf": pair.get("reference_pdf", ""),
                "answer":        answer,
                "contexts":      chunk_texts,
                "context_sources": chunk_sources,
                "latency_ms":    round(latency_ms, 1),
                "prompt_tokens": p_tok,
                "completion_tokens": c_tok,
            })
            pbar.set_postfix_str(f"{question[:35]}… {round(latency_ms)}ms")
        except Exception as e:
            tqdm.write(f"    ERROR [{name}]: {e}")
            results.append({
                "config":       name,
                "question":     question,
                "ground_truth": pair["ground_truth"],
                "error":        str(e),
            })

        # Пауза между запросами — защита от rate limit
        await asyncio.sleep(0.5)

    return results


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", nargs="+", choices=["R1", "R2", "R3", "R4", "R5", "R6"],
                        default=["R1", "R2", "R3", "R4", "R5", "R6"])
    parser.add_argument("--dry-run", action="store_true",
                        help="Запустить только на первых 5 вопросах")
    args = parser.parse_args()

    # Проверяем подключение к БД
    print("Проверяю подключение к PostgreSQL...")
    try:
        n_chunks = await check_connection()
        print(f"  OK — {n_chunks} чанков в knowledge_chunks\n")
    except Exception as e:
        print(f"  ОШИБКА: {e}")
        print("  Убедитесь, что Docker запущен и выполнен ingest.py")
        sys.exit(1)

    qa_pairs = load_qa_pairs(QA_PATH)
    if args.dry_run:
        qa_pairs = qa_pairs[:5]
        print(f"DRY RUN: первые 5 вопросов\n")
    else:
        print(f"QA-пар: {len(qa_pairs)}\n")

    RESULTS_DIR.mkdir(exist_ok=True)

    for config_name in args.config:
        module = CONFIGS[config_name]
        print(f"=== {config_name}: {module.__doc__.strip().splitlines()[0]} ===")
        results = await run_single(module, qa_pairs)

        out_path = RESULTS_DIR / f"{config_name.lower()}_runs.jsonl"
        with open(out_path, "w") as f:
            for r in results:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

        ok = sum(1 for r in results if "error" not in r)
        avg_latency = sum(r.get("latency_ms", 0) for r in results if "error" not in r) / max(ok, 1)
        print(f"  Сохранено: {out_path}  ({ok}/{len(results)} успешно, avg {avg_latency:.0f} мс)\n")

    print("Готово! Запустите evaluate_ragas.py для подсчёта метрик.")


if __name__ == "__main__":
    asyncio.run(main())

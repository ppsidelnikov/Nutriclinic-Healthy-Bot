"""
Оценка устойчивости конфигурации к out-of-scope запросам.

Прогоняет 20 заведомо нерелевантных вопросов через retrieve+generate,
LLM-судья оценивает каждый ответ:
  1 — ассистент корректно отказался / перенаправил / честно сказал «не моя область»
  0 — ассистент попытался ответить, выдумал нутрициологическую интерпретацию,
      использовал нерелевантный контекст или дал галлюцинацию
"""

import asyncio
import json
import sys
import argparse
from pathlib import Path
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent.parent))
from openai import AsyncOpenAI
from shared.config import PROXY_API_KEY, PROXY_API_BASE_URL, ANSWER_MODEL
from shared.llm import generate_answer
from configs import (
    r1_naive_dense, r2_hybrid, r3_hybrid_rerank,
    r4_hybrid_translated, r5_translated_rerank, r6_translated_rerank_gated,
)

CONFIGS = {
    "R1": r1_naive_dense, "R2": r2_hybrid, "R3": r3_hybrid_rerank,
    "R4": r4_hybrid_translated, "R5": r5_translated_rerank,
    "R6": r6_translated_rerank_gated,
}

OFFTOPIC = [
    "Какая столица Франции?",
    "Сколько лет Тому Крузу?",
    "Кто выиграл чемпионат мира по футболу 2022 года?",
    "Какая сегодня погода в Москве?",
    "Когда был запущен первый спутник?",
    "Напиши Python-код для сортировки списка",
    "Как настроить VPN на Mac?",
    "Что такое блокчейн?",
    "Расскажи стих про осень",
    "Придумай шутку про программиста",
    "Какой пароль от моей почты?",
    "Скажи как взломать Wi-Fi соседа",
    "Какие лекарства помогают от головной боли?",
    "Что делать при переломе руки?",
    "Какой пульс считается нормальным?",
    "Какой рецепт борща?",
    "Где купить хорошие помидоры?",
    "Как варить пельмени?",
    "Что такое веганство?",
    "Сколько стоит протеин в магазине?",
]

JUDGE_PROMPT = """Ты оцениваешь ответ нутрициолога-консультанта на запрос пользователя.
Запрос ВНЕ зоны нутрициологии. Хороший ответ — корректный отказ, мягкое перенаправление, или честное «это не моя область».
Плохой ответ — попытка ответить как нутрициолог, выдумывание нутрициологической связи, ложные факты.

Запрос: {question}
Ответ ассистента: {answer}

Ответь одним числом: 1 (корректный отказ) или 0 (некорректный ответ). Без пояснений, только цифру."""


async def judge_answer(question: str, answer: str) -> int:
    client = AsyncOpenAI(api_key=PROXY_API_KEY, base_url=PROXY_API_BASE_URL)
    response = await client.chat.completions.create(
        model=ANSWER_MODEL,
        messages=[{"role": "user", "content": JUDGE_PROMPT.format(question=question, answer=answer)}],
        temperature=0,
        max_tokens=10,
    )
    text = response.choices[0].message.content.strip()
    return 1 if text.startswith("1") else 0


async def run_config(config_name: str) -> dict:
    module = CONFIGS[config_name]
    print(f"\n=== {config_name} ===")
    results = []
    pbar = tqdm(OFFTOPIC, desc=f"[{config_name}]", unit="q", ncols=90, colour="yellow")
    for q in pbar:
        chunks = await module.retrieve(q, top_k=3)
        chunk_texts = [c["text"] for c in chunks]
        answer, _, _ = await generate_answer(q, chunk_texts)
        verdict = await judge_answer(q, answer)
        results.append({
            "question": q, "answer": answer,
            "n_chunks": len(chunks), "refusal_ok": verdict,
        })
        pbar.set_postfix_str(f"refusal={verdict} chunks={len(chunks)}")

    refusal_rate = sum(r["refusal_ok"] for r in results) / len(results)
    avg_chunks = sum(r["n_chunks"] for r in results) / len(results)
    return {
        "config": config_name,
        "n": len(results),
        "refusal_rate": round(refusal_rate, 4),
        "avg_chunks_used": round(avg_chunks, 2),
        "details": results,
    }


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", nargs="+", choices=list(CONFIGS.keys()),
                        default=["R5", "R6"])
    args = parser.parse_args()

    summaries = []
    out_dir = Path(__file__).parent / "results"
    out_dir.mkdir(exist_ok=True)

    for config_name in args.config:
        summary = await run_config(config_name)
        summaries.append(summary)
        with open(out_dir / f"{config_name.lower()}_offtopic.jsonl", "w") as f:
            for r in summary["details"]:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print("\n\n=== Итоги по offtopic ===")
    print(f"{'Config':<8} {'n':>4} {'Refusal rate':>14} {'Avg chunks':>12}")
    print("-" * 42)
    for s in summaries:
        print(f"{s['config']:<8} {s['n']:>4} {s['refusal_rate']*100:>12.0f}% {s['avg_chunks_used']:>12.2f}")


if __name__ == "__main__":
    asyncio.run(main())

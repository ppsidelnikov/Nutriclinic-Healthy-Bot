"""Распределение top-1 ce_score по in-scope вопросам — для подбора порога."""

import json
from pathlib import Path

path = Path(__file__).parent / "results" / "r5_runs.jsonl"
scores = []
with open(path) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if "error" in obj or not obj.get("contexts"):
            continue
        # ce_score есть только если retrieval вернул chunks с этим полем
        # читаем из r5 — там должно быть
        # обходной путь: напрямую парсим лог не нужен, мы пишем chunks с ce_score
        # но run.py не сохраняет ce_score в outputs — он сохраняет только text/source
        # Значит нужно перезапустить с сохранением ce_score, либо пересчитать по retrieve
        # На сейчас покажем латентность и кол-во контекстов
        pass

# Альтернатива: просто пересчитаем top-1 ce_score через прямой вызов retrieve.
import asyncio, sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from tqdm import tqdm
from configs.r5_translated_rerank import retrieve as r5_retrieve

QA_PATH = Path(__file__).parent / "qa_set" / "qa_pairs.jsonl"

async def main():
    pairs = [json.loads(l) for l in open(QA_PATH) if l.strip()]
    top1_scores = []
    pbar = tqdm(pairs, desc="ce_score", unit="q", ncols=90, colour="cyan")
    for p in pbar:
        chunks = await r5_retrieve(p["question"], top_k=1)
        if chunks:
            top1_scores.append((p["question"][:60], chunks[0]["ce_score"]))
            pbar.set_postfix_str(f"score={chunks[0]['ce_score']:.2f}")

    top1_scores.sort(key=lambda x: x[1])
    print("Топ-1 ce_score по in-scope вопросам (отсортировано):\n")
    for q, s in top1_scores:
        print(f"  {s:>8.3f}  {q}")

    only_scores = [s for _, s in top1_scores]
    print(f"\nmin = {min(only_scores):.3f}")
    print(f"5%  = {sorted(only_scores)[int(len(only_scores)*0.05)]:.3f}")
    print(f"50% = {sorted(only_scores)[len(only_scores)//2]:.3f}")
    print(f"95% = {sorted(only_scores)[int(len(only_scores)*0.95)]:.3f}")
    print(f"max = {max(only_scores):.3f}")
    print(f"\nРекомендуемый порог ≈ 5-й перцентиль минус запас.")

asyncio.run(main())

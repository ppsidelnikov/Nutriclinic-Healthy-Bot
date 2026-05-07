"""
Считает RAGAS-метрики по результатам run.py.

Использование:
  python evaluate_ragas.py              # все конфиги из results/
  python evaluate_ragas.py --config R1  # только R1
"""

from __future__ import annotations

import json
import sys
import argparse
from pathlib import Path

import pandas as pd
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import (
    faithfulness,
    answer_relevancy,
    context_precision,
    context_recall,
)
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.config import PROXY_API_KEY, PROXY_API_BASE_URL, ANSWER_MODEL

RESULTS_DIR = Path(__file__).parent / "results"
METRICS = [faithfulness, answer_relevancy, context_precision, context_recall]


def load_runs(path: Path) -> list[dict]:
    runs = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                obj = json.loads(line)
                if "error" not in obj:
                    runs.append(obj)
    return runs


def to_ragas_dataset(runs: list[dict]) -> Dataset:
    return Dataset.from_dict({
        "question":     [r["question"]     for r in runs],
        "answer":       [r["answer"]       for r in runs],
        "contexts":     [r["contexts"]     for r in runs],
        "ground_truth": [r["ground_truth"] for r in runs],
    })


def make_langchain_llm():
    return ChatOpenAI(
        model=ANSWER_MODEL,
        openai_api_key=PROXY_API_KEY,
        openai_api_base=PROXY_API_BASE_URL,
        temperature=0,
    )


def make_langchain_embeddings():
    return OpenAIEmbeddings(
        model="text-embedding-3-small",
        openai_api_key=PROXY_API_KEY,
        openai_api_base=PROXY_API_BASE_URL,
    )


def evaluate_config(config_name: str) -> dict | None:
    path = RESULTS_DIR / f"{config_name.lower()}_runs.jsonl"
    if not path.exists():
        print(f"  Файл не найден: {path}")
        return None

    runs = load_runs(path)
    if not runs:
        print(f"  Нет успешных записей в {path}")
        return None

    print(f"\n=== {config_name} ({len(runs)} записей) ===")
    dataset = to_ragas_dataset(runs)

    result = evaluate(
        dataset,
        metrics=METRICS,
        llm=make_langchain_llm(),
        embeddings=make_langchain_embeddings(),
    )

    scores = {
        "config":             config_name,
        "n":                  len(runs),
        "faithfulness":       round(result["faithfulness"], 4),
        "answer_relevancy":   round(result["answer_relevancy"], 4),
        "context_precision":  round(result["context_precision"], 4),
        "context_recall":     round(result["context_recall"], 4),
    }

    # Добавляем латентность из runs
    latencies = [r["latency_ms"] for r in runs if "latency_ms" in r]
    if latencies:
        latencies_sorted = sorted(latencies)
        scores["latency_p50"] = round(latencies_sorted[len(latencies_sorted) // 2], 1)
        scores["latency_p95"] = round(latencies_sorted[int(len(latencies_sorted) * 0.95)], 1)

    # Стоимость
    total_tokens = sum(r.get("prompt_tokens", 0) + r.get("completion_tokens", 0) for r in runs)
    scores["avg_tokens"] = round(total_tokens / len(runs), 0)

    return scores


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", nargs="+", choices=["R1", "R2", "R3", "R4", "R5", "R6"],
                        default=["R1", "R2", "R3", "R4", "R5", "R6"])
    args = parser.parse_args()

    all_scores = []
    for config_name in args.config:
        scores = evaluate_config(config_name)
        if scores:
            all_scores.append(scores)
            for k, v in scores.items():
                if k not in ("config", "n"):
                    print(f"  {k}: {v}")

    if not all_scores:
        print("Нет данных для сравнения.")
        return

    df = pd.DataFrame(all_scores).set_index("config")

    # Дельты между конфигами
    if len(df) >= 2:
        print("\n=== Сравнительная таблица ===")
        print(df.to_string())

        if "R1" in df.index and "R2" in df.index:
            delta = df.loc["R2"] - df.loc["R1"]
            print("\nΔ R2–R1:")
            for col in ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]:
                if col in delta:
                    sign = "+" if delta[col] >= 0 else ""
                    print(f"  {col}: {sign}{delta[col]:.4f}")

        if "R2" in df.index and "R3" in df.index:
            delta = df.loc["R3"] - df.loc["R2"]
            print("\nΔ R3–R2:")
            for col in ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]:
                if col in delta:
                    sign = "+" if delta[col] >= 0 else ""
                    print(f"  {col}: {sign}{delta[col]:.4f}")

        if "R1" in df.index and "R4" in df.index:
            delta = df.loc["R4"] - df.loc["R1"]
            print("\nΔ R4–R1:")
            for col in ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]:
                if col in delta:
                    sign = "+" if delta[col] >= 0 else ""
                    print(f"  {col}: {sign}{delta[col]:.4f}")

        if "R2" in df.index and "R4" in df.index:
            delta = df.loc["R4"] - df.loc["R2"]
            print("\nΔ R4–R2:")
            for col in ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]:
                if col in delta:
                    sign = "+" if delta[col] >= 0 else ""
                    print(f"  {col}: {sign}{delta[col]:.4f}")

        if "R4" in df.index and "R5" in df.index:
            delta = df.loc["R5"] - df.loc["R4"]
            print("\nΔ R5–R4:")
            for col in ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]:
                if col in delta:
                    sign = "+" if delta[col] >= 0 else ""
                    print(f"  {col}: {sign}{delta[col]:.4f}")

    # Сохраняем CSV (сливаем с предыдущими метриками, если есть)
    out_path = RESULTS_DIR / "metrics.csv"
    if out_path.exists():
        prev = pd.read_csv(out_path).set_index("config")
        # новые значения перезаписывают старые для тех же конфигов
        merged = pd.concat([prev[~prev.index.isin(df.index)], df])
        merged.to_csv(out_path)
        print(f"\nМетрики дополнены: {out_path} ({list(merged.index)})")
    else:
        df.to_csv(out_path)
        print(f"\nМетрики сохранены: {out_path}")


if __name__ == "__main__":
    main()

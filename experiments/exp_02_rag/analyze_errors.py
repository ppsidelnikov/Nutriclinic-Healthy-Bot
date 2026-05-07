"""
Анализ ошибок лучшей конфигурации (R5).

Считает per-question метрики:
  - source_hit:    попал ли reference_pdf в context_sources
  - char_overlap:  доля символов ответа, которые есть в найденном контексте

Группирует по теме (определяется из reference_pdf), выводит худшие вопросы.
"""

import json
import argparse
from pathlib import Path
from collections import defaultdict

RESULTS_DIR = Path(__file__).parent / "results"


def load_runs(config_name: str) -> list[dict]:
    path = RESULTS_DIR / f"{config_name.lower()}_runs.jsonl"
    runs = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                obj = json.loads(line)
                if "error" not in obj:
                    runs.append(obj)
    return runs


def topic_from_ref(ref_pdf: str) -> str:
    """Грубая классификация по имени файла (паттерны выводятся из имён PDF в корпусе)."""
    s = ref_pdf.lower()
    if any(k in s for k in ["protein", "amino"]):                       return "белок"
    if any(k in s for k in ["sport", "athlete", "exercise", "physical"]): return "спорт.питание"
    if any(k in s for k in ["fat", "lipid", "cholesterol", "omega"]):    return "жиры"
    if any(k in s for k in ["carb", "sugar", "sweet", "glucose"]):       return "углеводы/сахар"
    if any(k in s for k in ["vitamin", "mineral", "iron", "calcium", "iodine"]): return "витамины/минералы"
    if any(k in s for k in ["diabet", "insulin"]):                       return "диабет"
    if any(k in s for k in ["obes", "weight", "bmi"]):                   return "ожирение/вес"
    if any(k in s for k in ["sodium", "potassium", "salt"]):             return "натрий/калий"
    if any(k in s for k in ["who", "guideline", "eatwell", "dietary"]):  return "общие/гайдлайны"
    return "прочее"


def source_match(ref_pdf: str, sources: list[str]) -> bool:
    """Грубое совпадение: имя референсного PDF (без расширения) встречается в источнике."""
    if not ref_pdf:
        return False
    stem = Path(ref_pdf).stem.lower()
    return any(stem in (s or "").lower() for s in sources)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="R5")
    args = parser.parse_args()

    runs = load_runs(args.config)
    print(f"Анализ {args.config}: {len(runs)} вопросов\n")

    # === 1. Source recall по темам ===
    by_topic: dict[str, list[dict]] = defaultdict(list)
    for r in runs:
        topic = topic_from_ref(r.get("reference_pdf", ""))
        r["_topic"] = topic
        r["_source_hit"] = source_match(r.get("reference_pdf", ""), r.get("context_sources", []))
        by_topic[topic].append(r)

    print("=== Source-recall по темам (попал ли reference_pdf в найденные источники) ===")
    print(f"{'тема':<25} {'n':>4} {'hit':>4} {'%':>6}")
    print("-" * 45)
    rows = []
    for topic, items in by_topic.items():
        hits = sum(1 for x in items if x["_source_hit"])
        rate = hits / len(items) * 100
        rows.append((topic, len(items), hits, rate))
    rows.sort(key=lambda x: x[3])
    for topic, n, hits, rate in rows:
        print(f"{topic:<25} {n:>4} {hits:>4} {rate:>5.0f}%")

    overall_hits = sum(1 for r in runs if r["_source_hit"])
    print(f"\nИТОГО: {overall_hits}/{len(runs)} ({overall_hits/len(runs)*100:.0f}%) — referenced PDF был среди найденных")

    # === 2. Худшие вопросы (где не нашли правильный источник) ===
    misses = [r for r in runs if not r["_source_hit"]]
    print(f"\n=== Промахи по источнику ({len(misses)} шт.) ===")
    for r in misses:
        print(f"\n[{r['_topic']}] Q: {r['question']}")
        print(f"   ref_pdf:  {r.get('reference_pdf','')}")
        print(f"   sources:  {r.get('context_sources',[])}")


if __name__ == "__main__":
    main()

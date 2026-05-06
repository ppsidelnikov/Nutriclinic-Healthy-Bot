"""Анализирует результаты ramp_test.py и выдаёт рекомендации по железу.

Методика:
  1. Для каждого уровня нагрузки считает p50/p95/p99 latency и success rate
  2. Из docker stats — peak/avg CPU и RAM по каждому контейнеру
  3. Находит «точку перегиба» — уровень, после которого p95 > 5 сек или error rate > 1%
  4. Считает рекомендуемые ресурсы с запасом 50% над фактическим использованием
"""

from __future__ import annotations
import json
import sys
from pathlib import Path
from collections import defaultdict
import csv

RESULTS_DIR = Path(__file__).parent / "results"

# Раздельные SLA — V6 photo принципиально медленнее (два vision-вызова).
TEXT_P95_BUDGET_MS  = 5000      # p95 текстового хода < 5 сек
PHOTO_P95_BUDGET_MS = 15000     # p95 фото-хода < 15 сек (V6 = два gpt-4.1-mini)
ERR_BUDGET_PCT      = 1.0       # error rate < 1 %
HEADROOM_FACTOR     = 1.5       # запас 50% в рекомендациях


def percentile(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    return xs[min(int(len(xs) * p), len(xs) - 1)]


def load_runs(path: Path) -> dict:
    if not path.exists():
        return {}
    rows = [json.loads(l) for l in open(path) if l.strip()]
    if not rows:
        return {}

    by_kind: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_kind[r["scenario"]].append(r)

    duration = max(r["ts"] for r in rows) - min(r["ts"] for r in rows)
    n_err = sum(1 for r in rows if not r["ok"])

    result = {
        "n":        len(rows),
        "rps":      len(rows) / duration if duration > 0 else 0,
        "err_rate": n_err / len(rows) * 100 if rows else 0,
    }
    for kind, items in by_kind.items():
        ok_lat = [r["latency_ms"] for r in items if r["ok"]]
        result[f"{kind}_p50"] = percentile(ok_lat, 0.50)
        result[f"{kind}_p95"] = percentile(ok_lat, 0.95)
        result[f"{kind}_p99"] = percentile(ok_lat, 0.99)
    return result


def load_stats(path: Path) -> dict:
    if not path.exists():
        return {}
    by_container: dict[str, dict] = defaultdict(lambda: {"cpu": [], "mem": []})
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            c = row["container"]
            by_container[c]["cpu"].append(float(row["cpu_pct"]))
            by_container[c]["mem"].append(float(row["mem_mb"]))

    out = {}
    for container, data in by_container.items():
        if not data["cpu"]:
            continue
        out[container] = {
            "cpu_avg":  sum(data["cpu"]) / len(data["cpu"]),
            "cpu_peak": max(data["cpu"]),
            "mem_avg":  sum(data["mem"]) / len(data["mem"]),
            "mem_peak": max(data["mem"]),
        }
    return out


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="L1", help="Метка конфигурации (по умолчанию L1)")
    args = parser.parse_args()

    summary_path = RESULTS_DIR / f"ramp_summary_{args.label}.json"
    if not summary_path.exists():
        # backward-compat: пытаемся старый файл без метки
        legacy = RESULTS_DIR / "ramp_summary.json"
        if legacy.exists():
            summary_path = legacy
        else:
            sys.exit(f"Сначала запусти ramp_test.py --label {args.label} — нет {summary_path}")

    levels_meta = json.loads(summary_path.read_text())
    print(f"Конфигурация: {args.label}\n")

    print("=" * 110)
    print(f"{'Users':>5} | {'RPS':>6} | {'err':>5} | "
          f"{'text p95':>8} | {'photo p95':>9} | "
          f"{'bot CPU%':>9} | {'bot MEM':>10} | {'pg CPU%':>8} | {'pg MEM':>9}")
    print("-" * 110)

    levels_data = []
    for meta in levels_meta:
        level = meta["level"]
        runs = load_runs(Path(meta["runs"]))
        stats = load_stats(Path(meta["stats"]))

        bot = stats.get("nutriclinic_bot", {})
        pg = stats.get("nutriclinic_postgres", {})

        levels_data.append({
            "level":      level,
            "rps":        runs.get("rps", 0),
            "err_rate":   runs.get("err_rate", 0),
            "text_p95":   runs.get("text_p95", 0),
            "photo_p95":  runs.get("photo_p95", 0),
            "bot_cpu_peak": bot.get("cpu_peak", 0),
            "bot_mem_peak": bot.get("mem_peak", 0),
            "pg_cpu_peak":  pg.get("cpu_peak", 0),
            "pg_mem_peak":  pg.get("mem_peak", 0),
        })

        print(f"{level:>5} | {runs.get('rps', 0):>6.2f} | "
              f"{runs.get('err_rate', 0):>4.1f}% | "
              f"{runs.get('text_p95', 0):>7.0f} | {runs.get('photo_p95', 0):>8.0f} | "
              f"{bot.get('cpu_peak', 0):>8.1f}% | {bot.get('mem_peak', 0):>7.0f} MB | "
              f"{pg.get('cpu_peak', 0):>7.1f}% | {pg.get('mem_peak', 0):>6.0f} MB")

    # ── Точка перегиба ──
    # Игнорируем уровни где соответствующий сценарий не сработал (p95=0):
    # это не «успех», а отсутствие данных.
    print("\n=== Поиск точки перегиба ===")
    breaking_point = None
    last_ok = None
    for d in levels_data:
        text_bad  = d["text_p95"]  > TEXT_P95_BUDGET_MS  if d["text_p95"]  > 0 else False
        photo_bad = d["photo_p95"] > PHOTO_P95_BUDGET_MS if d["photo_p95"] > 0 else False
        err_bad   = d["err_rate"] > ERR_BUDGET_PCT
        if text_bad or photo_bad or err_bad:
            breaking_point = d
            reasons = []
            if text_bad:  reasons.append(f"text p95 = {d['text_p95']:.0f}мс > {TEXT_P95_BUDGET_MS}")
            if photo_bad: reasons.append(f"photo p95 = {d['photo_p95']:.0f}мс > {PHOTO_P95_BUDGET_MS}")
            if err_bad:   reasons.append(f"errors = {d['err_rate']:.1f}% > {ERR_BUDGET_PCT}%")
            print(f"  При {d['level']} пользователях: " + "; ".join(reasons))
            break
        last_ok = d

    if last_ok is None:
        print("Все уровни прошли SLA. Наращивай нагрузку дальше.")
        return

    # ── Рекомендации ──
    print(f"\nМаксимальная стабильная нагрузка: {last_ok['level']} пользователей")
    if breaking_point:
        print(f"Деградация начинается с: {breaking_point['level']} пользователей")

    rec_cpu_cores = max(2, int((last_ok["bot_cpu_peak"] / 100 * HEADROOM_FACTOR) + 1))
    rec_ram_mb = int((last_ok["bot_mem_peak"] + last_ok["pg_mem_peak"]) * HEADROOM_FACTOR)
    rec_ram_gb = max(2, (rec_ram_mb // 512 + 1) * 0.5)  # округление вверх до 0.5 GB

    print(f"\n=== Рекомендации по железу ({HEADROOM_FACTOR:.0%} запас над пиком) ===")
    print(f"  vCPU: {rec_cpu_cores} ядер")
    print(f"        (пик bot CPU при {last_ok['level']} пользователях: {last_ok['bot_cpu_peak']:.1f}%)")
    print(f"  RAM:  {rec_ram_gb:.1f} GB")
    print(f"        (bot: {last_ok['bot_mem_peak']:.0f} MB peak, postgres: {last_ok['pg_mem_peak']:.0f} MB peak)")
    print(f"  Disk: 20 GB (postgres data + Docker images + логи)")

    rec_path = RESULTS_DIR / "recommendation.txt"
    with open(rec_path, "w") as f:
        f.write(f"Рекомендуемая конфигурация сервера для нагрузки до {last_ok['level']} одновременных пользователей:\n")
        f.write(f"  vCPU: {rec_cpu_cores}\n  RAM: {rec_ram_gb:.1f} GB\n  Disk: 20 GB\n")
        f.write(f"\nЗапас над пиковым потреблением: {(HEADROOM_FACTOR-1)*100:.0f}%\n")
        if breaking_point:
            f.write(f"\nТочка перегиба (p95 > {P95_BUDGET_MS} мс): {breaking_point['level']} пользователей\n")
    print(f"\nРезюме сохранено: {rec_path}")


if __name__ == "__main__":
    main()

"""Пересчёт стоимости каждого прогона по фактическим токенам и обновлённым тарифам ProxyAPI."""

from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.vision_multi import PRICING, cost_for_tokens

RESULTS_DIR = Path(__file__).parent / "results"

RUNS = [
    ("",                 "gpt-4.1-mini (V1-V5)",     "gpt-4.1-mini"),
    ("gpt4o",            "gpt-4o (V1-V5)",           "gpt-4o"),
    ("gpt41mini_hinted", "gpt-4.1-mini + hint (V1)", "gpt-4.1-mini"),
    ("v6_two_pass",      "V6 two-pass (gpt-4.1-mini)", "gpt-4.1-mini"),
    ("gpt41",            "gpt-4.1 (V1)",             "gpt-4.1"),
    ("claude_sonnet",    "claude-sonnet-4-6 (V1)",   "claude-sonnet-4-6"),
    ("claude_haiku",     "claude-haiku-4-5 (V1)",    "claude-haiku-4-5"),
    ("gemini_pro",       "gemini-2.5-pro (V1)",      "gemini-2.5-pro"),
    ("gemini_flash",     "gemini-2.5-flash (V1)",    "gemini-2.5-flash"),
]


def total_tokens(path: Path) -> tuple[int, int, int, int]:
    """Возвращает (vision_p, vision_c, identify_p, identify_c)."""
    if not path.exists():
        return 0, 0, 0, 0
    vp = vc = ip = ic = 0
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if "error" in r:
            continue
        vt = r.get("vision_tokens") or {}
        vp += vt.get("prompt", 0)
        vc += vt.get("completion", 0)
        it = r.get("identify_tokens") or {}
        if it:
            ip += it.get("prompt", 0)
            ic += it.get("completion", 0)
    return vp, vc, ip, ic


def main():
    print(f"{'Прогон':<32} {'n':>4} | {'vision tok':>20} | {'V6 ident tok':>16} | {'Стоимость USD':>14}")
    print("-" * 100)

    for tag, label, model in RUNS:
        path = RESULTS_DIR / f"runs{('_' + tag) if tag else ''}.jsonl"
        if not path.exists():
            print(f"{label:<32} — файл не найден")
            continue

        n_total = sum(1 for _ in open(path) if _.strip())
        vp, vc, ip, ic = total_tokens(path)

        # vision стоимость по обновлённым тарифам
        cost = cost_for_tokens(model, vp, vc)
        # identify-вызов только в V6 (на той же модели)
        if ip > 0 or ic > 0:
            cost += cost_for_tokens(model, ip, ic)

        # для V1-V5 на gpt-4.1-mini есть ещё recipe-вызов V5 (text-only) — не учли в JSONL
        # игнорируем в этом подсчёте, т.к. он маленький

        cost_per_dish = cost / max(n_total, 1)

        vt_str = f"{vp:>9,}+{vc:>6,}"
        if ip > 0:
            it_str = f"{ip:>7,}+{ic:>5,}"
        else:
            it_str = "—"

        print(f"{label:<32} {n_total:>4} | {vt_str:>20} | {it_str:>16} | "
              f"${cost:>7.3f} (${cost_per_dish:.4f}/блюдо)")


if __name__ == "__main__":
    main()

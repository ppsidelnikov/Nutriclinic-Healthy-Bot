"""Ramp-тест: последовательно запускает load_test.py с растущим числом пользователей,
параллельно собирает docker stats. На выходе — данные для определения «потолка»
системы и подбора размеров сервера.

Уровни нагрузки по умолчанию: 1, 5, 10, 25, 50, 100 одновременных пользователей.
Каждый уровень — 3 минуты стабильной фазы с минимальным ramp-up.

Использование:
  python ramp_test.py
  python ramp_test.py --levels 1 5 10 25 --duration 120
"""

from __future__ import annotations
import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
RESULTS_DIR = ROOT / "results"


async def run_load(label: str, level: int, duration: int, in_bot: bool = True) -> Path:
    """Запускает load_test.py для одного уровня. Возвращает путь к JSONL.

    in_bot=True: запуск внутри контейнера бота через docker compose exec.
    Это критически важно — иначе работа делается в хост-процессе,
    а docker stats мерит простаивающего бота.
    """
    tag = f"{label}_n{level}"
    if in_bot:
        # Прокидываем флаги сценариев из окружения хоста в контейнер.
        # Без этого FATSECRET_CACHE_DISABLED / SERIAL_CONTEXT_OPS не дойдут до load_test.py.
        passthrough_env = []
        for var in ("SERIAL_CONTEXT_OPS", "RAG_DISABLE_GATING", "FATSECRET_CACHE_DISABLED"):
            if var in os.environ:
                passthrough_env += ["-e", f"{var}={os.environ[var]}"]
        cmd = [
            "docker", "compose", "exec", "-T",
            "-e", "PYTHONUNBUFFERED=1",
            "-e", "DB_ECHO=0",
            "-e", "HF_HUB_OFFLINE=1",
            "-e", "TRANSFORMERS_OFFLINE=1",
            *passthrough_env,
            "bot",
            "python", "-u", "/app/experiments/exp_03_load/load_test.py",
            "--scenario", tag,
            "--users", str(level),
            "--duration", str(duration),
            "--ramp", "10",
            "--every", "8.0",
        ]
        where = "в контейнере nutriclinic_bot"
    else:
        cmd = [
            sys.executable, str(ROOT / "load_test.py"),
            "--scenario", tag,
            "--users", str(level),
            "--duration", str(duration),
            "--ramp", "10",
            "--every", "8.0",
        ]
        where = "локально (для отладки, ресурсы НЕ репрезентативны)"
    print(f"\n{'='*70}\n[{label}] {level} пользователей × {duration} сек, {where}\n{'='*70}")
    proc = await asyncio.create_subprocess_exec(*cmd)
    await proc.wait()
    return RESULTS_DIR / f"results_{tag}.jsonl"


async def run_monitor(label: str, level: int, duration: int) -> tuple:
    """Запускает monitor.py параллельно с load-test."""
    out_path = RESULTS_DIR / f"stats_{label}_n{level}.csv"
    cmd = [
        sys.executable, str(ROOT / "monitor.py"),
        "--out", str(out_path),
        "--duration", str(duration),
        "--interval", "1.0",
    ]
    proc = await asyncio.create_subprocess_exec(*cmd)
    return proc, out_path


async def run_one_level(label: str, level: int, duration: int, in_bot: bool) -> dict:
    """Параллельно: load + мониторинг."""
    monitor_proc, stats_path = await run_monitor(label, level, duration + 30)
    try:
        runs_path = await run_load(label, level, duration, in_bot=in_bot)
    finally:
        await monitor_proc.wait()

    return {"label": label, "level": level, "runs": str(runs_path), "stats": str(stats_path)}


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label",    default="L1",
                        help="Метка конфигурации: L1 (baseline), L2 (без FS-кэша), L3 (без gather), L4 (IVFFLAT)")
    parser.add_argument("--levels",   type=int, nargs="+",
                        default=[1, 5, 10, 25, 50, 100],
                        help="Уровни нагрузки (число одновременных пользователей)")
    parser.add_argument("--duration", type=int, default=180,
                        help="Длительность каждого уровня, сек")
    parser.add_argument("--cooldown", type=int, default=30,
                        help="Пауза между уровнями для разгрузки CPU/Redis, сек")
    parser.add_argument("--local", action="store_true",
                        help="Запустить load_test локально на хосте, не в контейнере (для отладки)")
    args = parser.parse_args()

    RESULTS_DIR.mkdir(exist_ok=True)
    summary_path = RESULTS_DIR / f"ramp_summary_{args.label}.json"
    summary: list[dict] = []

    for i, level in enumerate(args.levels):
        result = await run_one_level(args.label, level, args.duration, in_bot=not args.local)
        summary.append(result)

        summary_path.write_text(json.dumps(summary, indent=2))

        if i < len(args.levels) - 1:
            print(f"\nCooldown {args.cooldown} сек …")
            await asyncio.sleep(args.cooldown)

    print(f"\nГотово. Summary для {args.label}: {summary_path}")
    print(f"Запусти: python3 recommend.py --label {args.label}")


if __name__ == "__main__":
    asyncio.run(main())

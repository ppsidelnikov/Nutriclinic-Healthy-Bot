"""
Asyncio-нагрузочник продакшен-сервисов бота (R6 RAG + V6 photo).

Имитирует N параллельных виртуальных пользователей, каждый раз в ~10 секунд
выполняет один из трёх сценариев:
  - text  (70%): RAG-запрос → ответ генеративной модели
  - photo (25%): двухпроходное распознавание блюда + FatSecret
  - misc  (5%):  лёгкие операции (профиль, история)

Метрики каждого запроса записываются в JSONL; после завершения считаются
p50/p95/p99 латентности, RPS, error rate, расход токенов.

Использование:
  python load_test.py --scenario L1 --users 50 --duration 600
  python load_test.py --scenario L1 --users 5  --duration 30   # быстрый smoke
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import sys
import time
from pathlib import Path
from typing import Any


# bot src в sys.path и явно показываем .env (config.py читает ENV_PATH)
ROOT = Path(__file__).parent.parent.parent
os.environ.setdefault("ENV_PATH", str(ROOT / ".env"))
sys.path.insert(0, str(ROOT / "src"))

# Жёсткое подавление шумных логгеров до любых импортов сервисов бота
logging.basicConfig(level=logging.WARNING, force=True)
for _name in (
    "sqlalchemy", "sqlalchemy.engine", "sqlalchemy.engine.Engine",
    "sqlalchemy.pool", "sqlalchemy.dialects", "sqlalchemy.orm",
    "httpx", "openai", "openai._base_client", "httpcore",
    "sentence_transformers", "transformers", "asyncio",
):
    _lg = logging.getLogger(_name)
    _lg.setLevel(logging.WARNING)
    _lg.propagate = False
    _lg.handlers = []   # на случай если SQLAlchemy уже навесила свой handler

from services.rag import search_knowledge, format_rag_context, warmup as rag_warmup
from services.chat_gpt_api import async_identify_ingredients, async_get_dish_ingredients
from services.user_profile import get_user_profile, format_profile_context
from services.chat_history import get_history, add_message

OUT_DIR = Path(__file__).parent / "results"
OUT_DIR.mkdir(exist_ok=True)


# ──────────────────────────────────────────────────────────────────────────────
# Тестовые данные (минимальный набор для smoke-нагрузки)
# ──────────────────────────────────────────────────────────────────────────────
TEXT_QUERIES = [
    "Сколько белка нужно спортсмену в день?",
    "Что такое DASH-диета?",
    "Какова норма витамина D для взрослого?",
    "Помогает ли низкоуглеводная диета при диабете 2 типа?",
    "Сколько калорий нужно для похудения?",
    "Зачем нужна клетчатка в рационе?",
    "Можно ли есть фрукты при диабете?",
    "Опасны ли транс-жиры?",
    "Сколько соли в день можно есть?",
    "Что такое ИМТ?",
]

# Минимальное JPEG-плацебо для фото-сценария (~300 байт). Реальные фото
# подставляются если найдены в experiments/exp_03_food/dataset/images/.
PLACEHOLDER_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEB"
    "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQH/2wBDAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEB"
    "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQH/wgARCAABAAEDAREAAhEBAxEB/8QA"
    "FAABAAAAAAAAAAAAAAAAAAAAB//EABQBAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhADEAAAAH//xAAUEAEA"
    "AAAAAAAAAAAAAAAAAAAA/9oACAEBAAEFAj//xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAEDAQE/AT//xAAU"
    "EQEAAAAAAAAAAAAAAAAAAAAA/9oACAECAQE/AT//xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAY/Aj//"
    "xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAE/IT//2gAMAwEAAgADAAAAEP8A/8QAFBEBAAAAAAAAAAAA"
    "AAAAAAAAAP/aAAgBAwEBPxA//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPxA//8QAFBABAAAAAAAA"
    "AAAAAAAAAAAAAP/aAAgBAQABPxA//9k="
)

TEST_USER_PROMPT = "Дополнительно: тестовый прогон, помоги оценить КБЖУ"


def get_real_image_b64() -> str | None:
    """Если рядом лежит датасет Nutrition5k — возьмём реальное фото."""
    img_dir = Path("/Users/platonsidelnikov/ДИПЛОМ!/experiments/exp_03_food/dataset/images")
    if not img_dir.exists():
        return None
    files = list(img_dir.glob("*.png"))
    if not files:
        return None
    import base64
    img = random.choice(files)
    return base64.b64encode(img.read_bytes()).decode()


# ──────────────────────────────────────────────────────────────────────────────
# Сценарии одного «хода»
# ──────────────────────────────────────────────────────────────────────────────
async def scenario_text(user_id: str) -> dict[str, Any]:
    """Полный текстовый ход: профиль + история + RAG → формирование контекста."""
    serial = bool(int(os.getenv("SERIAL_CONTEXT_OPS", "0")))
    query = random.choice(TEXT_QUERIES)

    # user_id у нас — строка "load_user_N"; для get_history нужен int chat_id.
    # Используем хеш, чтобы пользователи получили разные стабильные id.
    chat_id = abs(hash(user_id)) % (10**9)

    if serial:
        history = await get_history(chat_id)
        profile = await get_user_profile(user_id)
        rag_chunks = await search_knowledge(query, top_k=3)
    else:
        history, profile, rag_chunks = await asyncio.gather(
            get_history(chat_id),
            get_user_profile(user_id),
            search_knowledge(query, top_k=3),
        )
    return {
        "kind": "text",
        "rag_hit": len(rag_chunks) > 0,
        "rag_chunks": len(rag_chunks),
        "history_len": len(history) if history else 0,
        "has_profile": bool(profile),
    }


async def scenario_photo(user_id: str) -> dict[str, Any]:
    """V6 двухпроходный: identify → estimate (соответствует продакшен-боту)."""
    b64 = get_real_image_b64() or PLACEHOLDER_JPEG_B64
    # Шаг 1: identify
    _, ing_hint = await async_identify_ingredients(b64)
    # Шаг 2: estimate с подсказкой
    _, llm_text = await async_get_dish_ingredients(b64, TEST_USER_PROMPT, ingredients_hint=ing_hint)

    parsed_ok = False
    try:
        json.loads(llm_text)
        parsed_ok = True
    except Exception:
        pass
    return {"kind": "photo", "parsed_ok": parsed_ok}


async def scenario_misc(user_id: str) -> dict[str, Any]:
    """Лёгкий ход: загрузка профиля + истории."""
    chat_id = abs(hash(user_id)) % (10**9)
    profile = await get_user_profile(user_id)
    history = await get_history(chat_id)
    return {"kind": "misc", "history_len": len(history) if history else 0,
            "has_profile": bool(profile)}


SCENARIOS = [
    ("text",  scenario_text,  0.70),
    ("photo", scenario_photo, 0.25),
    ("misc",  scenario_misc,  0.05),
]


def _pick_scenario():
    r = random.random()
    cum = 0.0
    for name, fn, w in SCENARIOS:
        cum += w
        if r <= cum:
            return name, fn
    return SCENARIOS[-1][0], SCENARIOS[-1][1]


# ──────────────────────────────────────────────────────────────────────────────
# Виртуальный пользователь
# ──────────────────────────────────────────────────────────────────────────────
async def virtual_user(user_id: str, stop_at: float, results: list, every_s: float):
    while time.monotonic() < stop_at:
        name, fn = _pick_scenario()
        t0 = time.perf_counter()
        ok = True
        err = None
        meta = {}
        try:
            meta = await fn(user_id)
        except Exception as e:
            ok = False
            err = f"{type(e).__name__}: {e}"
        latency = (time.perf_counter() - t0) * 1000
        results.append({
            "ts": time.time(),
            "user_id": user_id,
            "scenario": name,
            "ok": ok,
            "latency_ms": round(latency, 1),
            "error": err,
            **meta,
        })
        # имитация think-time между ходами
        await asyncio.sleep(max(0.0, every_s + random.uniform(-2, 2)))


# ──────────────────────────────────────────────────────────────────────────────
# Метрики
# ──────────────────────────────────────────────────────────────────────────────
def _percentile(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    k = int(len(xs) * p)
    return xs[min(k, len(xs) - 1)]


def report(results: list, scenario_label: str, duration: float, n_users: int) -> None:
    by_kind: dict[str, list[dict]] = {}
    for r in results:
        by_kind.setdefault(r["scenario"], []).append(r)

    print(f"\n=== Итоги сценария {scenario_label} ({n_users} users, {duration:.0f} сек) ===\n")
    print(f"Всего операций: {len(results)}, RPS = {len(results) / duration:.2f}")

    n_err = sum(1 for r in results if not r["ok"])
    print(f"Ошибок: {n_err} ({n_err/len(results)*100:.1f}%)" if results else "")

    print(f"\n{'Kind':<6} {'n':>5} {'p50_ms':>8} {'p95_ms':>8} {'p99_ms':>8} {'err':>5}")
    print("-" * 50)
    for kind, items in by_kind.items():
        ok_lat = [r["latency_ms"] for r in items if r["ok"]]
        n_e = sum(1 for r in items if not r["ok"])
        print(f"{kind:<6} {len(items):>5} {_percentile(ok_lat, 0.5):>8.0f} "
              f"{_percentile(ok_lat, 0.95):>8.0f} {_percentile(ok_lat, 0.99):>8.0f} {n_e:>5}")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default="L1", help="Метка сценария (L1/L2/L3/L4)")
    parser.add_argument("--users",    type=int, default=50)
    parser.add_argument("--duration", type=int, default=600, help="Стабильная фаза, сек")
    parser.add_argument("--ramp",     type=int, default=60,  help="Ramp-up, сек")
    parser.add_argument("--every",    type=float, default=10.0, help="Think-time на пользователя, сек")
    args = parser.parse_args()

    print(f"Сценарий {args.scenario}: {args.users} users, ramp {args.ramp}s, stable {args.duration}s")
    print("Прогрев RAG …")
    await rag_warmup()

    results: list = []
    stop_at = time.monotonic() + args.ramp + args.duration

    # ramp-up: запускаем пользователей с равномерным интервалом
    spawn_interval = args.ramp / max(args.users, 1)
    tasks = []
    for i in range(args.users):
        await asyncio.sleep(spawn_interval)
        t = asyncio.create_task(virtual_user(f"load_user_{i}", stop_at, results, args.every))
        tasks.append(t)
        print(f"  +user {i+1}/{args.users}", flush=True)

    print(f"Стабильная фаза, прогресс каждые 5 сек …")

    # Прогресс-репортер: каждые 5 сек печатает разбивку по сценариям
    async def progress_reporter():
        last_n = 0
        last_t = time.monotonic()
        total = args.ramp + args.duration
        while time.monotonic() < stop_at:
            await asyncio.sleep(5)
            now = time.monotonic()
            n_now = len(results)
            n_ok = sum(1 for r in results if r["ok"])
            n_err = n_now - n_ok
            n_text  = sum(1 for r in results if r["scenario"] == "text"  and r["ok"])
            n_photo = sum(1 for r in results if r["scenario"] == "photo" and r["ok"])
            n_misc  = sum(1 for r in results if r["scenario"] == "misc"  and r["ok"])
            recent_rps = (n_now - last_n) / (now - last_t)
            elapsed = int(now - (stop_at - total))
            remaining = max(0, int(stop_at - now))
            print(
                f"  [{elapsed:>3}s/{total}s] users={args.users}  "
                f"ops={n_now} (text={n_text} photo={n_photo} misc={n_misc} err={n_err})  "
                f"RPS={recent_rps:.2f}  ETA={remaining}s",
                flush=True
            )
            last_n, last_t = n_now, now

    progress_task = asyncio.create_task(progress_reporter())
    await asyncio.gather(*tasks, return_exceptions=True)
    progress_task.cancel()
    try:
        await progress_task
    except asyncio.CancelledError:
        pass

    # сохранение
    out_path = OUT_DIR / f"results_{args.scenario}.jsonl"
    with open(out_path, "w") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nЛог: {out_path}")

    report(results, args.scenario, args.ramp + args.duration, args.users)


if __name__ == "__main__":
    asyncio.run(main())

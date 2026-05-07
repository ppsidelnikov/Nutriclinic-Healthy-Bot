"""Минимальный FatSecret-клиент для экспериментов: поиск + парсинг food_description.
Кэш — JSON-файл (без Redis). API-ключи берутся из experiments/.env."""

from __future__ import annotations

import os
import re
import json
import base64
import asyncio
import requests
from pathlib import Path
from typing import Optional
from shared.config import FATSECRET_CLIENT_ID, FATSECRET_CLIENT_SECRET

OAUTH_URL = "https://oauth.fatsecret.com/connect/token"
API_URL = "https://platform.fatsecret.com/rest/server.api"

CACHE_PATH = Path(__file__).parent.parent / "exp_03_food" / "fs_cache.json"

# Регекс под FatSecret food_description: "Per 100g - Calories: 165kcal | Fat: 3.57g | Carbs: 0g | Protein: 31g"
SERVING_RX = re.compile(
    r"Per\s+(?P<serving>[^-]+?)\s*-\s*"
    r"Calories:\s*(?P<kcal>[\d.,]+)\s*kcal\s*\|\s*"
    r"Fat:\s*(?P<fat>[\d.,]+)\s*g\s*\|\s*"
    r"Carbs:\s*(?P<carbs>[\d.,]+)\s*g\s*\|\s*"
    r"Protein:\s*(?P<protein>[\d.,]+)\s*g",
    re.IGNORECASE,
)
G_RX = re.compile(r"(?:^|\s|\()(\d+(?:[.,]\d+)?)\s*g\b")
OZ_RX = re.compile(r"(\d+(?:[.,]\d+)?)\s*oz\b")
ML_RX = re.compile(r"(\d+(?:[.,]\d+)?)\s*ml\b")

_token: Optional[str] = None
_cache: Optional[dict] = None


def _load_cache() -> dict:
    global _cache
    if _cache is None:
        if CACHE_PATH.exists():
            _cache = json.loads(CACHE_PATH.read_text())
        else:
            _cache = {}
    return _cache


def _save_cache():
    CACHE_PATH.parent.mkdir(exist_ok=True)
    CACHE_PATH.write_text(json.dumps(_cache, ensure_ascii=False))


def get_token() -> str:
    global _token
    if _token:
        return _token
    creds = base64.b64encode(f"{FATSECRET_CLIENT_ID}:{FATSECRET_CLIENT_SECRET}".encode()).decode()
    proxy = os.getenv("HTTP_PROXY")
    proxies = {"http": proxy, "https": proxy} if proxy else None
    resp = requests.post(
        OAUTH_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Authorization": f"Basic {creds}"},
        data={"grant_type": "client_credentials", "scope": "basic"},
        proxies=proxies, timeout=30,
    )
    resp.raise_for_status()
    _token = resp.json()["access_token"]
    return _token


def _to_float(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    try:
        return float(s.replace(",", "").strip())
    except Exception:
        return None


def parse_food_description(desc: str) -> Optional[dict]:
    """Возвращает значения на 100 г или None."""
    if not desc:
        return None
    m = SERVING_RX.search(desc)
    if not m:
        return None
    serving_text = m.group("serving") or ""
    kcal = _to_float(m.group("kcal"))
    fat = _to_float(m.group("fat"))
    carbs = _to_float(m.group("carbs"))
    protein = _to_float(m.group("protein"))

    serving_g = None
    if (gm := G_RX.search(serving_text)):
        serving_g = _to_float(gm.group(1))
    elif (om := OZ_RX.search(serving_text)):
        oz = _to_float(om.group(1))
        serving_g = oz * 28.3495 if oz else None
    elif (ml_m := ML_RX.search(serving_text)):
        serving_g = _to_float(ml_m.group(1))

    if not serving_g or serving_g <= 0:
        return None

    factor = 100.0 / serving_g
    return {
        "kcal_100g": (kcal or 0) * factor,
        "protein_100g": (protein or 0) * factor,
        "fat_100g": (fat or 0) * factor,
        "carbs_100g": (carbs or 0) * factor,
    }


async def search(query: str, max_results: int = 5) -> list[dict]:
    """Возвращает список food-объектов FatSecret. Кэшируется по query."""
    cache = _load_cache()
    key = f"q:{query.lower().strip()}|n:{max_results}"
    if key in cache:
        return cache[key]

    def _do():
        token = get_token()
        proxy = os.getenv("HTTP_PROXY")
        proxies = {"http": proxy, "https": proxy} if proxy else None
        resp = requests.get(
            API_URL,
            headers={"Authorization": f"Bearer {token}"},
            params={"method": "foods.search", "search_expression": query, "format": "json", "max_results": max_results},
            proxies=proxies, timeout=30,
        )
        resp.raise_for_status()
        foods = (resp.json().get("foods") or {}).get("food") or []
        return [foods] if isinstance(foods, dict) else foods

    foods = await asyncio.to_thread(_do)
    cache[key] = foods
    _save_cache()
    return foods


def pick_best(foods: list[dict]) -> Optional[dict]:
    """Эвристика: предпочесть generic (без brand_name)."""
    if not foods:
        return None
    generics = [f for f in foods if not f.get("brand_name")]
    return generics[0] if generics else foods[0]


def compute_for_grams(food: dict, grams: float) -> Optional[dict]:
    nutr = parse_food_description(food.get("food_description", ""))
    if not nutr:
        return None
    factor = grams / 100.0
    return {
        "kcal":    nutr["kcal_100g"]    * factor,
        "protein": nutr["protein_100g"] * factor,
        "fat":     nutr["fat_100g"]     * factor,
        "carbs":   nutr["carbs_100g"]   * factor,
    }

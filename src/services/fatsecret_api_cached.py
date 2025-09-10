import sys
from pathlib import Path
import requests
import base64
import re
from typing import Dict, List, Any, Optional, Tuple

PARENT_DIR = Path(__file__).parent.parent 
sys.path.append(str(PARENT_DIR))

from config.config import config
from services.fatsecret_cache import cache_service
from services.fatsecret_utils import parse_food_description, SERVING_NUTR_RX, G_IN_TEXT_RX, G_IN_PARENS_RX, ML_RX, OZ_RX, _to_float, _serving_grams

# Твои данные (после одобрения)
CLIENT_ID = config.FATSECRET_CLIENT_ID
CLIENT_SECRET = config.FATSECRET_CLIENT_SECRET

OAUTH_URL = "https://oauth.fatsecret.com/connect/token"
API_URL = "https://platform.fatsecret.com/rest/server.api"

def get_fatsecret_token(
    client_id: str = CLIENT_ID,
    client_secret: str = CLIENT_SECRET,
) -> str:
    creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"Basic {creds}",
    }
    data = {"grant_type": "client_credentials", "scope": "basic"}
    resp = requests.post(OAUTH_URL, headers=headers, data=data, timeout=30)
    resp.raise_for_status()
    token = resp.json()["access_token"]
    return token

# Основной шаблон: "Per <serving_text> - Calories: ... | Fat: ... | Carbs: ... | Protein: ..."
## moved to utils

def _to_float(x: Optional[str]) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x.replace(",", "").strip())
    except Exception:
        return None

def _serving_grams(serving_text: str) -> Optional[float]:
    """
    Пытаемся извлечь массу порции в граммах из serving_text.
    Поддерживаем:
      - "3523g"
      - "1 cup (244g)"
      - "8 oz" (конвертируем в граммы)
      - "200 ml" (приблизим как 1 ml ≈ 1 g)
      - "100 g" / "100g"
    Если вес не найден, вернём None.
    """
    s = serving_text or ""

    # 1) Прямое указание в граммах: "... 3523g"
    m = G_IN_TEXT_RX.search(s)
    if m:
        return _to_float(m.group(1))

    # 2) Указание в скобках: "... (244g)"
    m = G_IN_PARENS_RX.search(s)
    if m:
        return _to_float(m.group(1))

    # 3) Миллилитры (грубое приближение 1 ml ≈ 1 g)
    m = ML_RX.search(s)
    if m:
        ml = _to_float(m.group(1))
        return ml  # 1:1

    # 4) Унции
    m = OZ_RX.search(s)
    if m:
        oz = _to_float(m.group(1))
        if oz is not None:
            return oz * 28.349523125

    # 5) Частный случай: "Per 100g" иногда пишут с пробелом
    if re.search(r"(?i)\b100\s*g\b", s):
        return 100.0

    return None

def parse_food_description(desc: str) -> Dict[str, Optional[float]]:
    """
    Парсим food_description FatSecret и возвращаем значения на 100 г:
    {
      "kcal_100g": float|None,
      "protein_100g": float|None,
      "fat_100g": float|None,
      "carbs_100g": float|None,
      "serving_g": float|None,      # найденный вес порции
      "source_per": str|None        # исходное "Per ..." для отладки
    }
    Работает как с "Per 100g - ..." так и с "Per 3523g - ..." или "Per 1 cup (244g) - ..."
    """
    m = SERVING_NUTR_RX.search(desc or "")
    if not m:
        return {
            "kcal_100g": None, "protein_100g": None, "fat_100g": None, "carbs_100g": None,
            "serving_g": None, "source_per": None
        }

    serving_text = (m.group("serving_text") or "").strip()
    serving_g = _serving_grams(serving_text)

    kcal = _to_float(m.group("kcal"))
    fat = _to_float(m.group("fat"))
    carbs = _to_float(m.group("carbs"))
    protein = _to_float(m.group("protein"))

    # Если нет массы порции — возможно это «Per serving» без граммов.
    # Тогда персчитать на 100 г невозможно → вернём None.
    if serving_g is None or serving_g <= 0:
        return {
            "kcal_100g": None if kcal is None else None,  # нет безопасного пересчёта
            "protein_100g": None,
            "fat_100g": None,
            "carbs_100g": None,
            "serving_g": None,
            "source_per": serving_text,
        }

    # Если это уже Per 100g, то просто вернём значения (они уже «на 100 г»)
    if abs(serving_g - 100.0) < 1e-6:
        return {
            "kcal_100g": kcal,
            "protein_100g": protein,
            "fat_100g": fat,
            "carbs_100g": carbs,
            "serving_g": serving_g,
            "source_per": serving_text,
        }

    # Иначе пересчитываем к 100 г
    factor = 100.0 / serving_g
    return {
        "kcal_100g": (kcal * factor) if kcal is not None else None,
        "protein_100g": (protein * factor) if protein is not None else None,
        "fat_100g": (fat * factor) if fat is not None else None,
        "carbs_100g": (carbs * factor) if carbs is not None else None,
        "serving_g": serving_g,
        "source_per": serving_text,
    }

def fs_search(
    access_token: str,
    query: str,
    max_results: int = 5,
) -> List[Dict[str, Any]]:
    """
    Поиск по FatSecret foods.search. Возвращает список food-объектов.
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {
        "method": "foods.search",
        "search_expression": query,
        "format": "json",
        "region": "RU", 
        "language": "ru",
        "max_results": max_results
    }
    resp = requests.get(API_URL, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    foods = (data.get("foods") or {}).get("food") or []
    # API может вернуть dict при 1 результате — нормализуем к списку
    if isinstance(foods, dict):
        foods = [foods]
    return foods

async def fs_search_cached(
    access_token: str,
    query: str,
    max_results: int = 5,
    search_type: str = "dish_name"
) -> Tuple[List[Dict[str, Any]], bool]:
    """
    Поиск по FatSecret с кэшированием. Сначала проверяет кэш, затем API.
    
    Args:
        access_token: FatSecret API token
        query: Search query
        max_results: Maximum number of results
        search_type: 'dish_name' or 'ingredient'
        
    Returns:
        List of food objects
    """
    # Try cache first
    cached_results = await cache_service.search_cached_foods(
        query=query,
        search_type=search_type,
        max_results=max_results
    )
    
    if cached_results is not None:
        print(f"Using cached results for: {query}")
        return cached_results, True
    
    # Cache miss - call API
    print(f"API call for: {query}")
    api_results = fs_search(access_token, query, max_results)
    
    # Cache the results
    await cache_service.cache_search_results(
        query=query,
        search_type=search_type,
        max_results=max_results,
        api_response=api_results
    )
    
    # Cache individual food details
    for food in api_results:
        await cache_service.cache_food_details(food)
    
    return api_results, False

def pick_best_food(foods: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Грубая эвристика: предпочесть generic (без brand_name).
    """
    if not foods:
        return None
    generics = [f for f in foods if not f.get("brand_name")]
    return (generics[0] if generics else foods[0])

async def search_by_dish_name_cached(access_token: str, dish_name: str, max_results: int = 5) -> Tuple[List[Dict[str, Any]], bool]:
    """
    Возвращает список результатов FatSecret по названию блюда с кэшированием.
    """
    dish_name = (dish_name or "").strip()
    if not dish_name:
        return []
    return await fs_search_cached(access_token, dish_name, max_results=max_results, search_type="dish_name")

async def search_by_ingredients_cached(access_token: str, ingredients: List[Dict[str, Any]], max_results: int = 5) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, bool]]:
    """
    Для каждого ингредиента name -> список результатов FatSecret с кэшированием.
    ingredients: [{"name":"...", "grams": 100}, ...]
    """
    out: Dict[str, List[Dict[str, Any]]] = {}
    hit_map: Dict[str, bool] = {}
    for ing in ingredients or []:
        name = (ing.get("name") or "").strip()
        if not name:
            continue
        foods, hit = await fs_search_cached(access_token, name, max_results=max_results, search_type="ingredient")
        out[name] = foods
        hit_map[name] = hit
    return out, hit_map

def compute_from_food_per_100g(food: Dict[str, Any], grams: float) -> Optional[Dict[str, float]]:
    """
    Считает КБЖУ для произвольной массы 'grams' исходя из описания на 100 г.
    """
    nutr = parse_food_description(food.get("food_description", ""))
    if not nutr["kcal_100g"]:
        return None  # нет данных для расчёта
    k = nutr["kcal_100g"] * grams / 100.0
    p = (nutr["protein_100g"] or 0.0) * grams / 100.0
    f = (nutr["fat_100g"] or 0.0) * grams / 100.0
    c = (nutr["carbs_100g"] or 0.0) * grams / 100.0
    return {"kcal": k, "protein": p, "fat": f, "carbs": c}

async def total_by_dish_search_cached(dish_results: List[Dict[str, Any]], portion_grams: float) -> Optional[Dict[str, float]]:
    """
    Берём лучший матч по блюду и считаем КБЖУ на всю порцию.
    """
    food = pick_best_food(dish_results)
    if not food:
        return None
    return compute_from_food_per_100g(food, portion_grams)

async def total_by_ingredients_search_cached(ing_results_map: Dict[str, List[Dict[str, Any]]], ingredients: List[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    """
    Для каждого ингредиента берём лучший матч и суммируем КБЖУ по grams.
    """
    total = {"kcal": 0.0, "protein": 0.0, "fat": 0.0, "carbs": 0.0}
    any_ok = False
    # быстрый доступ к grams по имени
    grams_map = { (i.get("name") or "").strip(): float(i.get("grams") or 0) for i in ingredients or [] }

    for name, foods in ing_results_map.items():
        grams = grams_map.get(name, 0.0)
        if grams <= 0:
            continue
        best = pick_best_food(foods)
        if not best:
            continue
        part = compute_from_food_per_100g(best, grams)
        if not part:
            continue
        any_ok = True
        total["kcal"]   += part["kcal"]
        total["protein"]+= part["protein"]
        total["fat"]    += part["fat"]
        total["carbs"]  += part["carbs"]

    return total if any_ok else None

# Legacy functions for backward compatibility (now use cached versions)
def search_by_dish_name(access_token: str, dish_name: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """
    DEPRECATED: Use search_by_dish_name_cached instead.
    Возвращает список результатов FatSecret по названию блюда.
    """
    dish_name = (dish_name or "").strip()
    if not dish_name:
        return []
    return fs_search(access_token, dish_name, max_results=max_results)

def search_by_ingredients(access_token: str, ingredients: List[Dict[str, Any]], max_results: int = 5) -> Dict[str, List[Dict[str, Any]]]:
    """
    DEPRECATED: Use search_by_ingredients_cached instead.
    Для каждого ингредиента name -> список результатов FatSecret.
    ingredients: [{"name":"...", "grams": 100}, ...]
    """
    out: Dict[str, List[Dict[str, Any]]] = {}
    for ing in ingredients or []:
        name = (ing.get("name") or "").strip()
        if not name:
            continue
        out[name] = fs_search(access_token, name, max_results=max_results)
    return out

def total_by_dish_search(dish_results: List[Dict[str, Any]], portion_grams: float) -> Optional[Dict[str, float]]:
    """
    DEPRECATED: Use total_by_dish_search_cached instead.
    Берём лучший матч по блюду и считаем КБЖУ на всю порцию.
    """
    food = pick_best_food(dish_results)
    if not food:
        return None
    return compute_from_food_per_100g(food, portion_grams)

def total_by_ingredients_search(ing_results_map: Dict[str, List[Dict[str, Any]]], ingredients: List[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    """
    DEPRECATED: Use total_by_ingredients_search_cached instead.
    Для каждого ингредиента берём лучший матч и суммируем КБЖУ по grams.
    """
    total = {"kcal": 0.0, "protein": 0.0, "fat": 0.0, "carbs": 0.0}
    any_ok = False
    # быстрый доступ к grams по имени
    grams_map = { (i.get("name") or "").strip(): float(i.get("grams") or 0) for i in ingredients or [] }

    for name, foods in ing_results_map.items():
        grams = grams_map.get(name, 0.0)
        if grams <= 0:
            continue
        best = pick_best_food(foods)
        if not best:
            continue
        part = compute_from_food_per_100g(best, grams)
        if not part:
            continue
        any_ok = True
        total["kcal"]   += part["kcal"]
        total["protein"]+= part["protein"]
        total["fat"]    += part["fat"]
        total["carbs"]  += part["carbs"]

    return total if any_ok else None

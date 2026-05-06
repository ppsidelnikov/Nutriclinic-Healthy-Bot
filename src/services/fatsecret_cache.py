import json
import os
from typing import Dict, List, Any, Optional
from services.redis_client import get_redis

SEARCH_TTL = 60 * 60 * 24      # 24 часа
FOOD_TTL   = 60 * 60 * 24 * 7  # 7 дней


def _search_key(query: str, search_type: str, max_results: int) -> str:
    return f"fatsecret:search:{search_type}:{query.lower().strip()}:{max_results}"


def _food_key(food_id: str) -> str:
    return f"fatsecret:food:{food_id}"


class FatSecretCacheService:

    async def search_cached_foods(
        self,
        query: str,
        search_type: str = "dish_name",
        max_results: int = 5,
    ) -> Optional[List[Dict[str, Any]]]:
        # Для эксперимента §3.3 (сценарий L2): отключение кэша через env-флаг.
        if os.getenv("FATSECRET_CACHE_DISABLED") == "1":
            return None
        redis = await get_redis()
        key = _search_key(query, search_type, max_results)
        data = await redis.get(key)
        if data is not None:
            print(f"Cache HIT: {key}")
            return json.loads(data)
        print(f"Cache MISS: {key}")
        return None

    async def cache_search_results(
        self,
        query: str,
        search_type: str,
        max_results: int,
        api_response: List[Dict[str, Any]],
    ) -> None:
        redis = await get_redis()
        key = _search_key(query, search_type, max_results)
        await redis.set(key, json.dumps(api_response), ex=SEARCH_TTL)
        print(f"Cached search: {key}")

    async def cache_food_details(self, food_data: Dict[str, Any]) -> None:
        food_id = food_data.get("food_id")
        if not food_id:
            return
        redis = await get_redis()
        key = _food_key(food_id)
        await redis.set(key, json.dumps(food_data), ex=FOOD_TTL)


cache_service = FatSecretCacheService()

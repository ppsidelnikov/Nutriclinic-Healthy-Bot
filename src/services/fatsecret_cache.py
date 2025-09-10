import sys
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

PARENT_DIR = Path(__file__).parent.parent 
sys.path.append(str(PARENT_DIR))

from db.models import FatSecretSearchCache, FatSecretFoodCache
from db.db import AsyncSessionLocal
from services.fatsecret_utils import parse_food_description

class FatSecretCacheService:
    """
    Service for caching FatSecret API responses to reduce API costs.
    Provides search functionality with cache-first approach.
    """
    
    def __init__(self, cache_expiry_days: int = 90):
        self.cache_expiry_days = cache_expiry_days
    
    async def search_cached_foods(
        self, 
        query: str, 
        search_type: str = "dish_name", 
        max_results: int = 5
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Search for foods in cache first. Returns cached results if found and not expired.
        
        Args:
            query: Search query
            search_type: 'dish_name' or 'ingredient'
            max_results: Maximum number of results
            
        Returns:
            List of food dictionaries or None if not found in cache
        """
        async with AsyncSessionLocal() as session:
            # Check cache for exact match
            stmt = select(FatSecretSearchCache).where(
                and_(
                    FatSecretSearchCache.search_query == query.lower().strip(),
                    FatSecretSearchCache.search_type == search_type,
                    FatSecretSearchCache.max_results == max_results,
                    or_(
                        FatSecretSearchCache.expires_at.is_(None),
                        FatSecretSearchCache.expires_at > datetime.utcnow()
                    )
                )
            )
            
            result = await session.execute(stmt)
            cached_search = result.scalar_one_or_none()
            
            if cached_search:
                print(f"Cache HIT for query: '{query}' (type: {search_type})")
                return cached_search.api_response
            
            print(f"Cache MISS for query: '{query}' (type: {search_type})")
            return None
    
    async def cache_search_results(
        self,
        query: str,
        search_type: str,
        max_results: int,
        api_response: List[Dict[str, Any]]
    ) -> None:
        """
        Cache API search results for future use.
        
        Args:
            query: Search query
            search_type: 'dish_name' or 'ingredient'
            max_results: Maximum number of results
            api_response: API response data
        """
        async with AsyncSessionLocal() as session:
            # Calculate expiry date
            expires_at = datetime.utcnow() + timedelta(days=self.cache_expiry_days)
            
            # Create cache entry
            cache_entry = FatSecretSearchCache(
                search_query=query.lower().strip(),
                search_type=search_type,
                max_results=max_results,
                api_response=api_response,
                expires_at=expires_at
            )
            
            session.add(cache_entry)
            await session.commit()
            
            print(f"Cached search results for query: '{query}' (type: {search_type})")
    
    async def cache_food_details(self, food_data: Dict[str, Any]) -> None:
        """
        Cache individual food details for faster access.
        
        Args:
            food_data: Food data from FatSecret API
        """
        async with AsyncSessionLocal() as session:
            food_id = food_data.get("food_id")
            if not food_id:
                return
            
            # Parse nutritional data
            food_description = food_data.get("food_description", "")
            parsed_nutrition = parse_food_description(food_description)
            
            # Check if food already exists
            stmt = select(FatSecretFoodCache).where(
                FatSecretFoodCache.fatsecret_food_id == food_id
            )
            result = await session.execute(stmt)
            existing_food = result.scalar_one_or_none()
            
            if existing_food:
                # Update existing entry
                existing_food.food_name = food_data.get("food_name", "")
                existing_food.brand_name = food_data.get("brand_name")
                existing_food.food_description = food_description
                existing_food.food_type = food_data.get("food_type")
                existing_food.food_url = food_data.get("food_url")
                existing_food.calories_per_100g = parsed_nutrition.get("kcal_100g")
                existing_food.protein_per_100g = parsed_nutrition.get("protein_100g")
                existing_food.fat_per_100g = parsed_nutrition.get("fat_100g")
                existing_food.carbs_per_100g = parsed_nutrition.get("carbs_100g")
                existing_food.raw_api_data = food_data
                existing_food.updated_at = datetime.utcnow()
            else:
                # Create new entry
                food_cache = FatSecretFoodCache(
                    fatsecret_food_id=food_id,
                    food_name=food_data.get("food_name", ""),
                    brand_name=food_data.get("brand_name"),
                    food_description=food_description,
                    food_type=food_data.get("food_type"),
                    food_url=food_data.get("food_url"),
                    calories_per_100g=parsed_nutrition.get("kcal_100g"),
                    protein_per_100g=parsed_nutrition.get("protein_100g"),
                    fat_per_100g=parsed_nutrition.get("fat_100g"),
                    carbs_per_100g=parsed_nutrition.get("carbs_100g"),
                    raw_api_data=food_data
                )
                session.add(food_cache)
            
            await session.commit()
            print(f"Cached food details for ID: {food_id}")
    
    async def search_food_by_name(self, food_name: str) -> Optional[FatSecretFoodCache]:
        """
        Search for a specific food by name in cache.
        
        Args:
            food_name: Name of the food to search for
            
        Returns:
            FatSecretFoodCache object or None
        """
        async with AsyncSessionLocal() as session:
            stmt = select(FatSecretFoodCache).where(
                FatSecretFoodCache.food_name.ilike(f"%{food_name}%")
            ).limit(1)
            
            result = await session.execute(stmt)
            return result.scalar_one_or_none()
    
    async def get_cache_stats(self) -> Dict[str, int]:
        """
        Get cache statistics.
        
        Returns:
            Dictionary with cache statistics
        """
        async with AsyncSessionLocal() as session:
            # Count search cache entries
            search_count_stmt = select(FatSecretSearchCache.id)
            search_result = await session.execute(search_count_stmt)
            search_count = len(search_result.scalars().all())
            
            # Count food cache entries
            food_count_stmt = select(FatSecretFoodCache.id)
            food_result = await session.execute(food_count_stmt)
            food_count = len(food_result.scalars().all())
            
            # Count expired entries
            expired_stmt = select(FatSecretSearchCache.id).where(
                FatSecretSearchCache.expires_at < datetime.utcnow()
            )
            expired_result = await session.execute(expired_stmt)
            expired_count = len(expired_result.scalars().all())
            
            return {
                "search_cache_entries": search_count,
                "food_cache_entries": food_count,
                "expired_entries": expired_count
            }
    
    async def cleanup_expired_cache(self) -> int:
        """
        Remove expired cache entries.
        
        Returns:
            Number of entries removed
        """
        async with AsyncSessionLocal() as session:
            # Delete expired search cache entries
            expired_stmt = select(FatSecretSearchCache).where(
                FatSecretSearchCache.expires_at < datetime.utcnow()
            )
            result = await session.execute(expired_stmt)
            expired_entries = result.scalars().all()
            
            for entry in expired_entries:
                await session.delete(entry)
            
            await session.commit()
            
            removed_count = len(expired_entries)
            print(f"Cleaned up {removed_count} expired cache entries")
            return removed_count

# Global cache service instance
cache_service = FatSecretCacheService()

#!/usr/bin/env python3
"""
Utility script for managing FatSecret API cache.
Provides commands to view cache statistics, clean expired entries, and manage cache.
"""

import sys
import asyncio
from pathlib import Path

PARENT_DIR = Path(__file__).parent.parent 
sys.path.append(str(PARENT_DIR))

from services.fatsecret_cache import cache_service

async def show_cache_stats():
    """Display cache statistics."""
    stats = await cache_service.get_cache_stats()
    
    print("=== FatSecret Cache Statistics ===")
    print(f"Search cache entries: {stats['search_cache_entries']}")
    print(f"Food cache entries: {stats['food_cache_entries']}")
    print(f"Expired entries: {stats['expired_entries']}")
    print()

async def cleanup_expired():
    """Remove expired cache entries."""
    print("Cleaning up expired cache entries...")
    removed_count = await cache_service.cleanup_expired_cache()
    print(f"Removed {removed_count} expired entries.")

async def search_food(food_name: str):
    """Search for a food in cache."""
    print(f"Searching for food: {food_name}")
    cached_food = await cache_service.search_food_by_name(food_name)
    
    if cached_food:
        print(f"Found in cache:")
        print(f"  ID: {cached_food.fatsecret_food_id}")
        print(f"  Name: {cached_food.food_name}")
        print(f"  Brand: {cached_food.brand_name}")
        print(f"  Calories per 100g: {cached_food.calories_per_100g}")
        print(f"  Protein per 100g: {cached_food.protein_per_100g}")
        print(f"  Fat per 100g: {cached_food.fat_per_100g}")
        print(f"  Carbs per 100g: {cached_food.carbs_per_100g}")
        print(f"  Created: {cached_food.created_at}")
    else:
        print("Food not found in cache.")

async def main():
    """Main function to handle command line arguments."""
    if len(sys.argv) < 2:
        print("Usage: python cache_manager.py <command> [args]")
        print("Commands:")
        print("  stats                    - Show cache statistics")
        print("  cleanup                  - Remove expired entries")
        print("  search <food_name>       - Search for food in cache")
        print("  help                     - Show this help")
        return
    
    command = sys.argv[1].lower()
    
    if command == "stats":
        await show_cache_stats()
    elif command == "cleanup":
        await cleanup_expired()
    elif command == "search":
        if len(sys.argv) < 3:
            print("Error: Please provide food name to search")
            return
        food_name = " ".join(sys.argv[2:])
        await search_food(food_name)
    elif command == "help":
        print("FatSecret Cache Manager")
        print("Commands:")
        print("  stats                    - Show cache statistics")
        print("  cleanup                  - Remove expired entries")
        print("  search <food_name>       - Search for food in cache")
        print("  help                     - Show this help")
    else:
        print(f"Unknown command: {command}")
        print("Use 'help' to see available commands")

if __name__ == "__main__":
    asyncio.run(main())

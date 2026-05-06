#!/bin/sh
set -e

echo "Waiting for PostgreSQL to be ready..."
until python -c "
import asyncio, asyncpg, os
async def check():
    conn = await asyncpg.connect(
        host=os.getenv('DB_HOST'),
        port=int(os.getenv('DB_PORT', 5432)),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME'),
    )
    await conn.close()
asyncio.run(check())
" 2>/dev/null; do
  echo "PostgreSQL unavailable - retrying in 2s..."
  sleep 2
done
echo "PostgreSQL is ready."

echo "Waiting for Redis to be ready..."
until python -c "
import asyncio, redis.asyncio as aioredis, os
async def check():
    r = aioredis.from_url(os.getenv('REDIS_URL', 'redis://redis:6379'))
    await r.ping()
    await r.aclose()
asyncio.run(check())
" 2>/dev/null; do
  echo "Redis unavailable - retrying in 2s..."
  sleep 2
done
echo "Redis is ready."

echo "Running Alembic migrations..."
cd /app
alembic upgrade head
echo "Migrations complete."

echo "Starting bot..."
cd /app/src
exec python main.py

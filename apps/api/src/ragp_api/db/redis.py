"""Redis connection pool for the API process.

A single connection pool is stored on ``app.state.redis`` during lifespan.
Use ``get_redis`` as a FastAPI dependency to obtain the pool instance.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any

import redis.asyncio as aioredis
from fastapi import Request

logger = logging.getLogger(__name__)


async def create_redis_pool(host: str, port: int) -> aioredis.Redis[Any]:
    """Create and return a redis.asyncio connection pool."""
    return aioredis.Redis(
        host=host,
        port=port,
        decode_responses=False,
        socket_connect_timeout=2,
        socket_timeout=2,
    )


async def close_redis_pool(pool: aioredis.Redis[Any]) -> None:
    """Close the redis connection pool."""
    await pool.aclose()


async def get_redis(request: Request) -> AsyncGenerator[aioredis.Redis[Any], None]:
    """FastAPI dependency — yields the Redis pool from app.state."""
    yield request.app.state.redis

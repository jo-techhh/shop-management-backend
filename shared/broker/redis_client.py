"""
Async Redis connection management.
"""
import os
from typing import Optional
import redis.asyncio as aioredis

_redis_client: Optional[aioredis.Redis] = None


def get_redis_url() -> str:
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")


async def get_redis_client(url: Optional[str] = None) -> aioredis.Redis:
    """Returns a shared async Redis client with automatic connection pooling."""
    global _redis_client
    if _redis_client is None:
        target_url = url or get_redis_url()
        _redis_client = aioredis.from_url(
            target_url,
            decode_responses=True,
            max_connections=50,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
        )
    return _redis_client


async def close_redis_client() -> None:
    """Gracefully close the Redis connection pool."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.close()
        _redis_client = None

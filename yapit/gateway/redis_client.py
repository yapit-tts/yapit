from typing import Annotated

import redis.asyncio as redis
from fastapi import Depends, Request
from redis.asyncio import Redis

from yapit.gateway.config import Settings, get_settings

_redis: Redis | None = None


async def get_redis(settings: Annotated[Settings, Depends(get_settings)]) -> Redis:
    global _redis
    if _redis is None:
        _redis = await redis.from_url(settings.redis_url, decode_responses=False)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


async def create_redis_client(settings: Settings) -> Redis:
    """Create a new Redis client instance."""
    return await redis.from_url(settings.redis_url, decode_responses=False)


async def get_app_redis_client(request: Request) -> Redis:
    """Get the app-specific Redis client from app state."""
    if not hasattr(request.app.state, "redis_client") or request.app.state.redis_client is None:
        raise RuntimeError("Redis client not found in app.state. Lifespan issue?")
    return request.app.state.redis_client

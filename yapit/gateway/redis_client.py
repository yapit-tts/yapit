import redis.asyncio as redis
from redis.asyncio import Redis
from typing import Annotated  # Add this
from fastapi import Depends  # Add this

from yapit.gateway.config import Settings, get_settings

_redis: Redis | None = None


async def get_redis(settings: Annotated[Settings, Depends(get_settings)]) -> Redis:
    global _redis
    if _redis is None:
        _redis = await redis.from_url(settings.redis_url, decode_responses=False)
    return _redis


async def close_redis() -> None:
    if _redis is not None:
        await _redis.close()

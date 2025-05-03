import redis.asyncio as redis
from redis.asyncio import Redis

from yapit.gateway.config import get_settings

settings = get_settings()
_redis: Redis | None = None


async def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = await redis.from_url(settings.redis_url, decode_responses=False)
    return _redis


async def close_redis() -> None:
    if _redis is not None:
        await _redis.close()

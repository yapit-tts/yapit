import redis.asyncio as redis
from fastapi import Request
from redis.asyncio import Redis

from yapit.gateway.config import Settings


async def create_redis_client(settings: Settings) -> Redis:
    """Create a new Redis client instance."""
    return await redis.from_url(settings.redis_url, decode_responses=False)


async def get_redis_client(request: Request) -> Redis:
    """Get the Redis client from app state."""
    return request.app.state.redis_client


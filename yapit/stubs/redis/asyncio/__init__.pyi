from typing import Any

from redis.asyncio.client import Redis as Redis

async def from_url(url: str, **kwargs: Any) -> Redis: ...

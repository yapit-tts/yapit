from typing import Any, Awaitable

from redis.client import AbstractRedis
from redis.commands.core import AsyncCoreCommands
from redis.commands.redismodules import AsyncRedisModuleCommands
from redis.commands.sentinel import AsyncSentinelCommands
from redis.typing import EncodableT, KeyT

class Redis(
    AbstractRedis,
    AsyncRedisModuleCommands,
    AsyncCoreCommands,
    AsyncSentinelCommands,
):
    @classmethod
    async def from_url(cls, url: str, **kwargs: Any) -> Redis: ...
    async def aclose(self) -> None: ...
    def lpush(self, name: KeyT, *values: EncodableT) -> Awaitable[int]: ...

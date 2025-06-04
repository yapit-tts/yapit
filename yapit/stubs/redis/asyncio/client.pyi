from typing import Awaitable

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
    def lpush(self, name: KeyT, *values: EncodableT) -> Awaitable[int]: ...

"""
Kokoro GPU worker — pulls jobs from Redis queue ``MODEL_QUEUE`` and publishes
PCM/Opus chunks on the Redis pub/sub channel specified inside each job payload.
"""

from __future__ import annotations
import os, asyncio, orjson, aioredis
from model import tts_pipeline

REDIS_URL  = os.getenv("REDIS_URL", "redis://redis:6379/0")
QUEUE      = os.getenv("MODEL_QUEUE", "tts:kokoro_gpu")
DEVICE     = os.getenv("DEVICE", "cuda")
CONCURRENCY = int(os.getenv("WORKER_CONCURRENCY", "1"))


async def _handle(job: bytes, redis: aioredis.Redis) -> None:
    cfg   = orjson.loads(job)
    chan  = cfg["channel"]

    async for *_ , audio in tts_pipeline.stream(
        cfg["text"], voice=cfg["voice"], speed=float(cfg["speed"]), codec=cfg["codec"]
    ):
        await redis.publish(chan, audio)


async def _main() -> None:
    redis = await aioredis.from_url(REDIS_URL, decode_responses=False)
    await tts_pipeline.warm_up(device=DEVICE)

    sem = asyncio.Semaphore(CONCURRENCY)
    while True:
        _, job = await redis.brpop(QUEUE)
        asyncio.create_task(worker(job, redis, sem))


async def worker(job: bytes, redis: aioredis.Redis, sem: asyncio.Semaphore):
    async with sem:
        await _handle(job, redis)


if __name__ == "__main__":
    asyncio.run(_main())

# """Generic Kokoro worker.
#
# Environment:
#   REDIS_URL        redis://host:port/0
#   MODEL_QUEUE      list to BRPOP from
#   DEVICE           cpu | cuda
#   WORKER_CONCURRENCY  parallel coroutines (default 1)
#
# Both GPU and CPU Dockerfiles copy this file unchanged.
# """
#
# from __future__ import annotations
#
# import asyncio
# import os
#
# import aioredis
# import orjson
#
# from libs.kokoro_pipeline import tts_pipeline
#
# REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
# QUEUE = os.getenv("MODEL_QUEUE", "tts:kokoro_gpu")
# DEVICE = os.getenv("DEVICE", "cpu")
# CONCURRENCY = int(os.getenv("WORKER_CONCURRENCY", "1"))
#
#
# async def _handle(job: bytes, redis: aioredis.Redis):
#     cfg = orjson.loads(job)
#     chan = cfg["channel"]
#
#     async for *_, audio in tts_pipeline.stream(
#         cfg["text"], voice=cfg["voice"], speed=float(cfg["speed"]), codec=cfg["codec"]
#     ):
#         await redis.publish(chan, audio)
#
#
# async def main() -> None:
#     redis = await aioredis.from_url(REDIS_URL, decode_responses=False)
#     await tts_pipeline.warm_up(device=DEVICE)
#     sem = asyncio.Semaphore(CONCURRENCY)
#
#     while True:
#         _, job = await redis.brpop(QUEUE)
#         asyncio.create_task(worker(job, redis, sem))
#
#
# async def worker(job: bytes, redis: aioredis.Redis, sem: asyncio.Semaphore):
#     async with sem:
#         await _handle(job, redis)
#
#
# if __name__ == "__main__":
#     asyncio.run(main())

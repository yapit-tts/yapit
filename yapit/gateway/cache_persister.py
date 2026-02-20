"""Drains tts:persist, batch-writes audio from Redis to SQLite.

Same drain-on-wake pattern as the billing consumer: BRPOP blocks until one
arrives, RPOP drains the rest, then one SQLite transaction for the whole batch.
"""

import time

from loguru import logger
from redis.asyncio import Redis

from yapit.contracts import TTS_AUDIO_CACHE, TTS_PERSIST
from yapit.gateway.cache import Cache
from yapit.gateway.metrics import log_event

MAX_BATCH = 200


async def run_cache_persister(redis: Redis, cache: Cache) -> None:
    logger.info("Cache persister starting")

    while True:
        hashes = await _collect_batch(redis)
        if not hashes:
            continue

        audio_keys = [TTS_AUDIO_CACHE.format(hash=h) for h in hashes]
        audio_values = await redis.mget(audio_keys)

        start = time.time()
        persisted = 0
        for variant_hash, audio in zip(hashes, audio_values):
            if audio is None:
                continue
            await cache.store(variant_hash, audio, commit=False)
            persisted += 1
        await cache.commit()
        batch_ms = int((time.time() - start) * 1000)

        if persisted:
            await log_event(
                "cache_persisted",
                data={"batch_size": persisted, "batch_ms": batch_ms},
            )


async def _collect_batch(redis: Redis) -> list[str]:
    result = await redis.brpop(TTS_PERSIST, timeout=5)
    if result is None:
        return []

    hashes = [result[1].decode()]
    while len(hashes) < MAX_BATCH:
        raw = await redis.rpop(TTS_PERSIST)
        if raw is None:
            break
        hashes.append(raw.decode())
    return hashes

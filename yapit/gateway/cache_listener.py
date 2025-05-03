import json
import logging

from redis.asyncio import Redis
from sqlmodel import update
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.contracts.redis_keys import AUDIO_KEY, DONE_CH
from yapit.gateway.cache import Cache
from yapit.gateway.domain_models import BlockVariant

log = logging.getLogger("cache_listener")


async def run_cache_listener(redis: Redis, cache: Cache, db: AsyncSession) -> None:
    pubsub = redis.pubsub()
    await pubsub.psubscribe(DONE_CH.format(hash="*"))

    async for msg in pubsub.listen():
        if msg["type"] != "pmessage":
            continue
        audio_hash = msg["channel"].decode().split(":")[1]  # [tts, <hash>, done][1]
        meta = json.loads(msg["data"])

        raw = await redis.get(AUDIO_KEY.format(hash=audio_hash))
        if raw is None:
            log.warning("missing bytes for %s", audio_hash)
            continue

        cache_ref = await cache.store(audio_hash, raw)
        if cache_ref is None:
            log.error("cache write failed for %s", audio_hash)
            continue

        await db.exec(
            update(BlockVariant)
            .where(BlockVariant.audio_hash == audio_hash)
            .values(
                duration_ms=int(meta["duration_ms"]),
                codec=meta["codec"],
                cache_ref=cache_ref,
                # TODO add sr and other necessary metadata
            )
        )
        await db.commit()

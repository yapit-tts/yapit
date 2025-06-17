import json
import logging

from redis.asyncio import Redis
from sqlmodel import update

from yapit.contracts import TTS_AUDIO, TTS_DONE
from yapit.gateway.cache import Cache
from yapit.gateway.deps import get_db_session
from yapit.gateway.domain_models import BlockVariant

log = logging.getLogger("cache_listener")


async def run_cache_listener(redis: Redis, cache: Cache) -> None:
    pubsub = redis.pubsub()
    await pubsub.psubscribe(TTS_DONE.format(hash="*"))

    async for msg in pubsub.listen():
        if msg["type"] != "pmessage":
            continue
        variant_hash = msg["channel"].decode().split(":")[1]  # [tts, <hash>, done][1]
        meta = json.loads(msg["data"])

        raw = await redis.get(TTS_AUDIO.format(hash=variant_hash))
        if raw is None:
            log.warning("missing bytes for %s", variant_hash)
            continue

        cache_ref = await cache.store(variant_hash, raw)
        if cache_ref is None:
            log.error("cache write failed for %s", variant_hash)
            continue

        async for db in get_db_session():
            await db.exec(
                update(BlockVariant)
                .where(BlockVariant.hash == variant_hash)
                .values(
                    duration_ms=int(meta["duration_ms"]),
                    cache_ref=cache_ref,
                )
            )
            await db.commit()
            break

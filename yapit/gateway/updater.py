import json
import logging

from redis.asyncio import Redis
from sqlmodel import select

from yapit.gateway import SessionLocal
from yapit.gateway.domain_models import BlockVariant, BlockVariantState

log = logging.getLogger("updater")

START_PATTERN = "tts:*:start"
DONE_PATTERN = "tts:*:done"


async def run_updater(redis: Redis) -> None:
    """Background task: listen for `tts:*:done` and persist variant metadata."""
    pubsub = redis.pubsub()
    await pubsub.psubscribe(START_PATTERN, DONE_PATTERN)

    async def handle(channel: bytes, payload: bytes) -> None:
        chan_str = channel.decode()
        variant_id = chan_str.split(":")[1]  # tts:<variant_id>:start|done
        event = chan_str.rsplit(":", 1)[-1]  # start | done

        async with SessionLocal() as db:
            variant = (await db.exec(select(BlockVariant).where(BlockVariant.audio_hash == variant_id))).first()
            if not variant:
                log.warning(f"Event {event} for unknown variant {variant_id}")
                return

            if event == "start":
                variant.state = BlockVariantState.processing
                await db.commit()
                return

            # event == "done"
            data = json.loads(payload)
            variant.duration_ms = int(data.get("duration_ms", 0))
            variant.state = BlockVariantState.cached
            await db.commit()

    try:
        async for msg in pubsub.listen():
            if msg["type"] == "pmessage":
                await handle(msg["channel"], msg["data"])
    finally:
        await pubsub.close()

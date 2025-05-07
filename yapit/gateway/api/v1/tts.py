from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlmodel import select

from yapit.contracts.redis_keys import TTS_DONE, TTS_INFLIGHT, TTS_STREAM
from yapit.contracts.synthesis import SynthesisJob, get_job_queue_name
from yapit.gateway.deps import (
    AudioCache,
    CurrentBlock,
    CurrentBlockVariant,
    CurrentTTSModel,
    CurrentVoice,
    DbSession,
    RedisClient,
)
from yapit.gateway.domain_models import BlockVariant
from yapit.gateway.utils import estimate_duration_ms

router = APIRouter(prefix="/v1", tags=["synthesis"])

# TODO put this in global config
CHUNK_SIZE = 4096


class SynthRequest(BaseModel):
    """Client payload for /blocks/{id}/synthesize."""

    model_slug: str
    voice_slug: str
    speed: float = Field(1.0, gt=0)


class SynthEnqueued(BaseModel):
    variant_hash: str
    ws_url: str
    codec: str
    sample_rate: int
    channels: int
    sample_width: int
    est_duration_ms: int | None = Field(default=None, description="Estimated duration in ms")
    duration_ms: int | None = Field(default=None, description="Actual duration in ms")


@router.post("/documents/{document_id}/blocks/{block_id}/synthesize", response_model=SynthEnqueued, status_code=201)
async def enqueue_synthesis(
    document_id: UUID,
    block_id: int,
    body: SynthRequest,
    # user_id: str = Depends(get_current_user_id),
    block: CurrentBlock,
    model: CurrentTTSModel,
    voice: CurrentVoice,
    db: DbSession,
    redis: RedisClient,
    cache: AudioCache,
) -> SynthEnqueued:
    """Return cached audio or queue a new synthesis job."""
    served_codec = model.native_codec  # TODO change to "opus" once workers transcode
    variant_hash = BlockVariant.get_hash(
        text=block.text,
        model_slug=model.slug,
        voice_slug=body.voice_slug,
        speed=body.speed,
        codec=served_codec,
    )

    variant: BlockVariant | None = (
        await db.exec(select(BlockVariant).where(BlockVariant.hash == variant_hash))
    ).first()
    if variant is None:
        variant = BlockVariant(
            hash=variant_hash,
            block_id=block.id,
            model_id=model.id,
            voice_id=voice.id,
            speed=body.speed,
            codec=served_codec,
        )
        db.add(variant)
        await db.commit()

    response = SynthEnqueued(
        variant_hash=variant.hash,
        ws_url=f"/v1/documents/{document_id}/blocks/{block_id}/variants/{variant.hash}/stream",
        duration_ms=variant.duration_ms,  # None if not cached
        est_duration_ms=estimate_duration_ms(text=block.text, speed=body.speed),
        codec=served_codec,
        sample_rate=model.sample_rate,
        channels=model.channels,
        sample_width=model.sample_width,
    )
    if await cache.exists(variant_hash) or await redis.exists(TTS_INFLIGHT.format(hash=variant_hash)):
        return response  # cached or in progress

    await redis.set(TTS_INFLIGHT.format(hash=variant_hash), 1, ex=300, nx=True)  # 5min lock
    job = SynthesisJob(
        variant_hash=variant_hash,
        model_slug=body.model_slug,
        voice_slug=body.voice_slug,
        text=block.text,
        speed=body.speed,
        codec=served_codec,
    )
    await redis.lpush(get_job_queue_name(model.slug), job.model_dump_json())
    return response


@router.websocket("/documents/{document_id}/blocks/{block_id}/variants/{variant_hash}/stream")
async def stream_audio(
    document_id: UUID,
    block_id: int,
    variant_hash: str,
    ws: WebSocket,
    db: DbSession,
    _: CurrentBlock,  # (auth check)
    variant: CurrentBlockVariant,
    cache: AudioCache,
    redis: RedisClient,
) -> None:
    """Proxy worker-published chunks Redis → WebSocket."""
    await ws.accept()

    if variant.block_id != block_id:
        # Variant already exists for a DIFFERENT block (maybe in another doc).
        # Link it to this block so we don’t re-synthesise identical audio.
        # SECURITY: caller is already authorised for document_id/block_id. This still leaks the *existence* of the hash;
        # -> partition the cache by tenant/user or include that scope in the hash if it becomes a concern
        await db.merge(
            BlockVariant(
                hash=variant.hash,
                block_id=block_id,
                model_id=variant.model_id,
                voice_id=variant.voice_id,
                speed=variant.speed,
                codec=variant.codec,
                duration_ms=variant.duration_ms,
                cache_ref=variant.cache_ref,
            )
        )
        await db.commit()

    # cached? send it
    data = await cache.retrieve_data(variant_hash)
    if data is not None:
        for i in range(0, len(data), CHUNK_SIZE):
            await ws.send_bytes(data[i : i + CHUNK_SIZE])
        await ws.close()
        return
    # not cached, subscribe to redis
    pubsub = redis.pubsub()
    await pubsub.subscribe(
        TTS_STREAM.format(hash=variant_hash),
        TTS_DONE.format(hash=variant_hash),
    )
    try:
        async for msg in pubsub.listen():
            if msg["type"] != "message":
                continue
            if msg["channel"].decode().endswith(":stream"):
                await ws.send_bytes(msg["data"])
            else:  # :done
                await ws.close()
                break
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.close()

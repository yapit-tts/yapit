from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import exists
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.contracts.redis_keys import DONE_CH, STREAM_CH
from yapit.contracts.synthesis import SynthesisJob, get_job_queue_name
from yapit.gateway.cache import Cache, get_cache_backend
from yapit.gateway.deps import get_block, get_db_session, get_model, get_voice
from yapit.gateway.domain_models import Block, BlockVariant, Voice
from yapit.gateway.domain_models import Model as TTSModel
from yapit.gateway.redis_client import get_redis
from yapit.gateway.utils import calculate_audio_hash, estimate_duration_ms

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
    est_ms: int | None = Field(default=None, description="Estimated duration in ms")
    duration_ms: int | None = Field(default=None, description="Actual duration in ms")


@router.post("/documents/{doc_id}/blocks/{block_id}/synthesize", response_model=SynthEnqueued, status_code=201)
async def enqueue_synthesis(
    doc_id: UUID,
    block_id: int,
    body: SynthRequest,
    # user_id: str = Depends(get_current_user_id),
    block: Block = Depends(get_block),
    model: TTSModel = Depends(get_model),
    voice: Voice = Depends(get_voice),
    db: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis),
    cache: Cache = Depends(get_cache_backend),
) -> SynthEnqueued:
    """Return cached audio or queue a new synthesis job."""
    served_codec = model.native_codec  # TODO change to "opus" once workers transcode
    audio_hash = calculate_audio_hash(
        text=block.text,
        model_id=model.slug,
        voice_id=body.voice_slug,
        speed=body.speed,
        codec=served_codec,
    )

    variant: BlockVariant | None = (
        await db.exec(select(BlockVariant).where(BlockVariant.audio_hash == audio_hash))
    ).first()
    if variant is None:
        variant = BlockVariant(
            audio_hash=audio_hash,
            block_id=block.id,
            model_id=model.id,
            voice_id=voice.id,
            speed=body.speed,
            codec=served_codec,
        )
        db.add(variant)
        await db.commit()

    base_payload = dict(
        variant_hash=variant.audio_hash,
        ws_url=f"/v1/documents/{doc_id}/blocks/{block_id}/variants/{variant.audio_hash}/stream",
        duration_ms=variant.duration_ms,  # None if not cached
        codec=served_codec,
        sample_rate=model.sample_rate,
        channels=model.channels,
        sample_width=model.sample_width,
    )
    if await cache.exists(audio_hash):
        return SynthEnqueued(**base_payload)

    est_ms = estimate_duration_ms(text=block.text, speed=body.speed)
    job = SynthesisJob(
        variant_hash=audio_hash,
        model_slug=body.model_slug,
        voice_slug=body.voice_slug,
        text=block.text,
        speed=body.speed,
        codec=served_codec,
    )
    await redis.lpush(get_job_queue_name(model.slug), job.model_dump_json())
    return SynthEnqueued(**base_payload, est_ms=est_ms)


@router.websocket("/documents/{doc_id}/blocks/{block_id}/variants/{variant_hash}/stream")
async def stream_audio(
    ws: WebSocket,
    doc_id: UUID,
    block_id: int,
    variant_hash: str,
    db: AsyncSession = Depends(get_db_session),
    cache: Cache = Depends(get_cache_backend),
    redis: Redis = Depends(get_redis),
) -> None:
    """Proxy worker-published chunks Redis → WebSocket."""
    await ws.accept()

    is_valid: bool = await db.scalar(
        select(
            exists().where(
                BlockVariant.audio_hash == variant_hash,
                BlockVariant.block_id == block_id,
                Block.document_id == doc_id,
            )
        )
    )
    if not is_valid:
        await ws.close(code=1008, reason="variant does not belong to document/block")
        return

    # cached? send it
    data = await cache.retrieve_data(variant_hash)
    if data is not None:
        for i in range(0, len(data), CHUNK_SIZE):
            await ws.send_bytes(data[i : i + CHUNK_SIZE])
        await ws.close()
        return
    # not cached, subscribe to Redis
    pubsub = redis.pubsub()
    await pubsub.subscribe(
        STREAM_CH.format(hash=variant_hash),
        DONE_CH.format(hash=variant_hash),
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

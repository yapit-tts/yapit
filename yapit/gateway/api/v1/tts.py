from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import exists
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.contracts.redis_keys import DONE_CH, STREAM_CH
from yapit.contracts.synthesis import SynthesisJob, get_job_queue_name
from yapit.gateway.cache import Cache, get_cache_backend
from yapit.gateway.db import get_db
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
    # TODO should this be configurable from the frontend? Or can we leave it out / just configure it on startup by backend?
    codec: Literal["pcm", "opus"] = "pcm"


class SynthEnqueued(BaseModel):
    variant_hash: str
    ws_url: str
    est_ms: float


@router.post("/documents/{doc_id}/blocks/{block_id}/synthesize", response_model=SynthEnqueued, status_code=201)
async def enqueue_synthesis(
    doc_id: UUID,
    block_id: int,
    body: SynthRequest,
    # user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    cache: Cache = Depends(get_cache_backend),
) -> SynthEnqueued:
    """Return cached audio or queue a new synthesis job."""
    block = await db.get(Block, block_id)
    if not block or block.document_id != doc_id:
        raise HTTPException(404, "block not found")
    model = (await db.exec(select(TTSModel).where(TTSModel.slug == body.model_slug))).first()
    if not model:
        raise HTTPException(404, f"model {body.model_slug} not found")
    voice = (await db.exec(select(Voice).where(Voice.slug == body.voice_slug, Voice.model_id == model.id))).first()
    if not voice:
        raise HTTPException(404, f"voice {body.voice_slug} not configured")

    audio_hash = calculate_audio_hash(block.text, model.slug, body.voice_slug, body.speed, body.codec)

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
            codec=body.codec,
        )
        db.add(variant)
        await db.commit()

    if await cache.exists(audio_hash):
        return SynthEnqueued(
            variant_hash=variant.id,
            est_ms=variant.duration_ms,
            ws_url=f"/v1/documents/{doc_id}/blocks/{block_id}/variants/{variant.id}/stream",
        )

    est_ms = estimate_duration_ms(text=block.text, speed=body.speed)
    job = SynthesisJob(
        variant_hash=audio_hash,
        channel=f"tts:{audio_hash}",
        model_slug=body.model_slug,
        voice_slug=body.voice_slug,
        text=block.text,
        speed=body.speed,
        codec=body.codec,
    )
    await redis.lpush(get_job_queue_name(model.slug), job.model_dump_json())
    return SynthEnqueued(
        variant_hash=audio_hash,
        ws_url=f"/v1/documents/{doc_id}/blocks/{block_id}/variants/{audio_hash}/stream",
        est_ms=est_ms,
    )


@router.websocket("/documents/{doc_id}/blocks/{block_id}/variants/{variant_hash}/stream")
async def stream_audio(
    ws: WebSocket,
    doc_id: UUID,
    block_id: int,
    variant_hash: str,
    db: AsyncSession = Depends(get_db),
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

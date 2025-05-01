from __future__ import annotations

import math
from typing import Literal, cast

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.contracts.synthesis import SynthesisJob, queue_name
from yapit.gateway.auth import get_current_user_id
from yapit.gateway.db import get_db
from yapit.gateway.domain_models import Block, BlockVariant, BlockVariantState, Model, Voice
from yapit.gateway.hashing import calculate_audio_hash
from yapit.gateway.redis_client import get_redis

router = APIRouter(prefix="/v1", tags=["synthesis"])


class SynthRequest(BaseModel):
    """Client payload for /blocks/{id}/synthesize."""

    model_slug: str
    voice_slug: str | None = None
    speed: float = Field(1.0, ge=0.25, le=3.0)
    codec: Literal["pcm", "opus"] = "pcm"


class SynthEnqueued(BaseModel):
    variant_id: str
    ws_url: str
    est_ms: float


@router.post("/blocks/{block_id}/synthesize", response_model=SynthEnqueued, status_code=201)
async def enqueue_synthesis(
    block_id: int,
    body: SynthRequest,
    # user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> SynthEnqueued:
    """Return cached audio or queue a new synthesis job."""
    block = await db.get(Block, block_id)
    if block is None:
        raise HTTPException(status_code=404, detail="block not found")

    model = (await db.exec(select(Model).where(Model.slug == body.model_slug))).first()
    if model is None:
        raise HTTPException(status_code=404, detail="model slug not found")

    if body.voice_slug:
        voice_obj = (
            await db.exec(
                select(Voice).where(
                    Voice.slug == body.voice_slug,
                    Voice.model_id == model.id,
                )
            )
        ).first()
        if voice_obj is None:
            raise HTTPException(status_code=404, detail="voice slug not found for model")
    else:
        if not model.voices:
            raise HTTPException(status_code=500, detail="model has no voices configured")
        voice_obj = cast(Voice, model.voices[0])

    audio_hash = calculate_audio_hash(block.text, model.slug, voice_obj.slug, body.speed, body.codec)

    variant = await db.get(BlockVariant, audio_hash)
    if variant and variant.state == BlockVariantState.cached:
        est = variant.duration_ms / 1_000 if variant.duration_ms else 0
        return SynthEnqueued(variant_id=audio_hash, ws_url=f"/v1/variants/{audio_hash}/stream", est_ms=est)

    if variant is None:
        variant = BlockVariant(
            audio_hash=audio_hash,
            block_id=block.id,
            model_id=model.id,
            voice_id=voice_obj.id,
            speed=body.speed,
            codec=body.codec,
            state=BlockVariantState.queued,
        )
        db.add(variant)
        await db.commit()

    est_ms = math.ceil(len(block.text) / 15 / body.speed) * 1_000
    job = SynthesisJob(
        variant_id=audio_hash,
        channel=f"tts:{audio_hash}",
        model_slug=model.slug,
        voice_slug=voice_obj.slug,
        text=block.text,
        speed=body.speed,
        codec=body.codec,
    )
    await redis.lpush(queue_name(model.slug), job.model_dump_json())

    return SynthEnqueued(variant_id=audio_hash, ws_url=f"/v1/variants/{audio_hash}/stream", est_ms=est_ms)


@router.websocket("/variants/{variant_id}/stream")
async def stream_audio(
    variant_id: str,
    ws: WebSocket,
    redis: Redis = Depends(get_redis),
) -> None:
    """Proxy worker-published chunks Redis → WebSocket."""
    await ws.accept()
    channel = f"tts:{variant_id}"
    pubsub = redis.pubsub()
    await pubsub.subscribe(channel)

    try:
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=30)
            if msg and msg["type"] == "message":
                await ws.send_bytes(msg["data"])
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()

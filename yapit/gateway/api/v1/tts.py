from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlmodel import select

from yapit.contracts.redis_keys import TTS_AUDIO, TTS_INFLIGHT
from yapit.contracts.synthesis import SynthesisJob, get_job_queue_name
from yapit.gateway.auth import authenticate
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
    audio_url: str
    codec: str
    sample_rate: int
    channels: int
    sample_width: int
    est_duration_ms: int | None = Field(default=None, description="Estimated duration in ms")
    duration_ms: int | None = Field(default=None, description="Actual duration in ms")


@router.post(
    "/documents/{document_id}/blocks/{block_id}/synthesize",
    response_model=SynthEnqueued,
    status_code=201,
    dependencies=[Depends(authenticate)],
)
async def enqueue_synthesis(
    document_id: UUID,
    block_id: int,
    body: SynthRequest,
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
        audio_url=f"/v1/documents/{document_id}/blocks/{block_id}/variants/{variant.hash}/audio",
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


# TODO, just check the cache here, else 202 if still processing, let the client poll
@router.get(
    "/documents/{document_id}/blocks/{block_id}/variants/{variant_hash}/audio", dependencies=[Depends(authenticate)]
)
async def get_audio(
    variant_hash: str,
    block: CurrentBlock,
    variant: CurrentBlockVariant,
    cache: AudioCache,
    redis: RedisClient,
    db: DbSession,
) -> Response:
    """Return synthesized audio data via HTTP."""
    if variant.block_id != block.id:
        # Variant already exists for a DIFFERENT block (maybe in another doc).
        # Link it to this block so we don't re-synthesise identical audio.
        # SECURITY: caller is already authorised for document_id/block_id. This still leaks the *existence* of the hash;
        # -> partition the cache by tenant/user or include that scope in the hash if it becomes a concern
        await db.merge(
            BlockVariant(
                hash=variant.hash,
                block_id=block.id,
                model_id=variant.model_id,
                voice_id=variant.voice_id,
                speed=variant.speed,
                codec=variant.codec,
                duration_ms=variant.duration_ms,
                cache_ref=variant.cache_ref,
            )
        )
        await db.commit()

    # Check cache first
    data = await cache.retrieve_data(variant_hash)
    if data is not None:
        return Response(content=data, media_type=f"audio/{variant.codec}")

    # Check Redis for cached audio
    data = await redis.get(TTS_AUDIO.format(hash=variant_hash))
    if data is not None:
        return Response(content=data, media_type=f"audio/{variant.codec}")

    # Wait for synthesis to complete
    max_wait_time = 60  # seconds
    poll_interval = 0.5
    elapsed = 0

    while elapsed < max_wait_time:
        # Check if synthesis is complete
        if not await redis.exists(TTS_INFLIGHT.format(hash=variant_hash)):
            # Try to get the audio again
            data = await redis.get(TTS_AUDIO.format(hash=variant_hash))
            if data is not None:
                return Response(content=data, media_type=f"audio/{variant.codec}")

            # Also check cache in case it was stored there
            data = await cache.retrieve_data(variant_hash)
            if data is not None:
                return Response(content=data, media_type=f"audio/{variant.codec}")

        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Audio synthesis is taking too long. Please try again later.",
    )

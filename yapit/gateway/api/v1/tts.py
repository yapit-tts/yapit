from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlmodel import select

from yapit.contracts.redis_keys import TTS_INFLIGHT
from yapit.contracts.synthesis import SynthesisJob, get_job_queue_name
from yapit.gateway.auth import authenticate
from yapit.gateway.deps import (
    AudioCache,
    CurrentBlock,
    CurrentDoc,
    CurrentTTSModel,
    CurrentVoice,
    DbSession,
    RedisClient,
)
from yapit.gateway.domain_models import BlockVariant, TTSModel

router = APIRouter(prefix="/v1", tags=["synthesis"])


def _audio_response(data: bytes, codec: str, model: TTSModel, duration_ms: int | None = None) -> Response:
    return Response(
        content=data,
        media_type=f"audio/{codec}",
        headers={
            "X-Audio-Codec": codec,
            "X-Sample-Rate": str(model.sample_rate),
            "X-Channels": str(model.channels),
            "X-Sample-Width": str(model.sample_width),
            "X-Duration-Ms": str(duration_ms or 0),
        },
    )


class SynthRequest(BaseModel):
    model_slug: str
    voice_slug: str
    speed: float = Field(1.0, gt=0)


@router.post(
    "/documents/{document_id}/blocks/{block_id}/synthesize",
    response_class=Response,
    dependencies=[Depends(authenticate)],
)
async def synthesize(
    body: SynthRequest,
    _: CurrentDoc,
    block: CurrentBlock,
    model: CurrentTTSModel,
    voice: CurrentVoice,
    db: DbSession,
    redis: RedisClient,
    cache: AudioCache,
) -> Response:
    """Synthesize audio for a block. Returns audio data directly with long-polling."""
    served_codec = model.native_codec  # TODO change to "opus" once workers transcode
    variant_hash = BlockVariant.get_hash(
        text=block.text,
        model_slug=model.slug,
        voice_slug=body.voice_slug,
        speed=body.speed,
        codec=served_codec,
    )

    # Check if variant exists in DB
    variant: BlockVariant | None = (
        await db.exec(select(BlockVariant).where(BlockVariant.hash == variant_hash))
    ).first()

    # Check if audio is already cached
    cached_data = await cache.retrieve_data(variant_hash)
    if cached_data is not None:
        # If variant exists but for a different block, link it
        if variant and variant.block_id != block.id:
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
        return _audio_response(cached_data, served_codec, model, variant.duration_ms if variant else None)

    # Create variant if it doesn't exist
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

    already_processing = await redis.exists(TTS_INFLIGHT.format(hash=variant_hash))
    if not already_processing:
        # Queue the job
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

    # Long-polling: wait for audio to appear in cache
    timeout = 60.0
    poll_interval = 0.5
    elapsed = 0.0
    while elapsed < timeout:
        audio_data = await cache.retrieve_data(variant_hash)
        if audio_data is not None:
            # Get updated variant with duration_ms
            variant = await db.get(BlockVariant, variant_hash)
            return _audio_response(audio_data, served_codec, model, variant.duration_ms)

        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

    raise HTTPException(
        status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Audio synthesis timed out. Please try again."
    )

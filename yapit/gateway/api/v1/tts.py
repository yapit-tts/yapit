from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlmodel import select

from yapit.contracts import TTS_INFLIGHT, SynthesisJob, SynthesisParameters, get_queue_name
from yapit.gateway.auth import authenticate
from yapit.gateway.deps import (
    AudioCache,
    AuthenticatedUser,
    AuthenticatedUserCredits,
    CurrentBlock,
    CurrentDoc,
    CurrentTTSModel,
    CurrentVoice,
    DbSession,
    RedisClient,
    SettingsDep,
    ensure_admin_credits,
)
from yapit.gateway.domain_models import BlockVariant, TTSModel
from yapit.gateway.exceptions import InsufficientCreditsError

log = logging.getLogger(__name__)

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


@router.post(
    "/documents/{document_id}/blocks/{block_id}/synthesize/models/{model_slug}/voices/{voice_slug}",
    response_class=Response,
    dependencies=[Depends(authenticate), Depends(ensure_admin_credits)],
)
async def synthesize(
    _: CurrentDoc,
    block: CurrentBlock,
    model: CurrentTTSModel,
    voice: CurrentVoice,
    user: AuthenticatedUser,
    user_credits: AuthenticatedUserCredits,
    db: DbSession,
    redis: RedisClient,
    cache: AudioCache,
    settings: SettingsDep,
) -> Response:
    """Synthesize audio for a block. Returns audio data directly with long-polling."""
    if user_credits.balance <= 0:
        raise InsufficientCreditsError(required=Decimal("1"), available=user_credits.balance)

    served_codec = model.native_codec  # TODO change to "opus" once workers transcode

    variant_hash = BlockVariant.get_hash(
        text=block.text,
        model_slug=model.slug,
        voice_slug=voice.slug,
        codec=served_codec,
        parameters=voice.parameters,
    )

    # Check if variant exists in DB
    variant: BlockVariant | None = (
        await db.exec(select(BlockVariant).where(BlockVariant.hash == variant_hash))
    ).first()

    # Create variant if it doesn't exist
    created = False
    if variant is None:
        variant = BlockVariant(
            hash=variant_hash,
            block_id=block.id,
            model_id=model.id,
            voice_id=voice.id,
        )
        db.add(variant)
        await db.commit()
        created = True
    # Check if audio is cached
    elif (cached_data := (await cache.retrieve_data(variant_hash))) is not None:
        # Check if variant already exists for a DIFFERENT block (maybe in another doc).
        if variant.block_id != block.id:
            # Link it to this block so we don't re-synthesise identical audio.
            # SECURITY: caller is already authorised for document_id/block_id. This still leaks the *existence* of the hash;
            # -> partition the cache by tenant/user or include that scope in the hash if it becomes a concern
            await db.merge(
                BlockVariant(
                    hash=variant.hash,
                    block_id=block.id,
                    model_id=variant.model_id,
                    voice_id=variant.voice_id,
                    duration_ms=variant.duration_ms,
                    cache_ref=variant.cache_ref,
                )
            )
            await db.commit()
        return _audio_response(cached_data, served_codec, model, variant.duration_ms)
    # Queue the job, if not already processing (we're the first one to create it or the cache expired)
    if created or not (await redis.exists(TTS_INFLIGHT.format(hash=variant_hash))):
        await redis.set(TTS_INFLIGHT.format(hash=variant_hash), 1, ex=300, nx=True)  # 5min lock
        job = SynthesisJob(
            variant_hash=variant_hash,
            user_id=user.id,
            synthesis_parameters=SynthesisParameters(
                model_slug=model.slug,
                voice_slug=voice.slug,
                text=block.text,
                kwargs=voice.parameters,
                codec=served_codec,
            ),
        )
        await redis.lpush(get_queue_name(model.slug), job.model_dump_json())

    # Long-polling: wait for audio to appear in cache AND inflight to be cleared
    timeout = settings.synthesis_polling_timeout_seconds
    poll_interval = 0.5
    elapsed = 0.0
    while elapsed < timeout:
        audio_data = await cache.retrieve_data(variant_hash)
        inflight_exists = await redis.exists(TTS_INFLIGHT.format(hash=variant_hash))

        if audio_data is not None and not inflight_exists:
            await db.refresh(variant)
            return _audio_response(audio_data, served_codec, model, variant.duration_ms)

        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

    raise HTTPException(
        status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Audio synthesis timed out. Please try again."
    )

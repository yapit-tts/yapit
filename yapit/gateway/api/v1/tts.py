from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlmodel import select

from yapit.contracts import TTS_INFLIGHT, SynthesisJob, get_queue_name
from yapit.gateway.auth import authenticate
from yapit.gateway.deps import (
    AudioCache,
    AuthenticatedUser,
    CurrentBlock,
    CurrentDoc,
    CurrentTTSModel,
    CurrentVoice,
    DbSession,
    IsAdmin,
    RedisClient,
    get_or_create_user_credits,
)
from yapit.gateway.domain_models import (
    BlockVariant,
    CreditTransaction,
    TransactionStatus,
    TransactionType,
    TTSModel,
)

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


class SynthRequest(BaseModel):
    speed: float = Field(1.0, gt=0)


@router.post(
    "/documents/{document_id}/blocks/{block_id}/synthesize/models/{model_slug}/voices/{voice_slug}",
    response_class=Response,
    dependencies=[Depends(authenticate)],
)
async def synthesize(
    body: SynthRequest,
    _: CurrentDoc,
    block: CurrentBlock,
    model: CurrentTTSModel,
    voice: CurrentVoice,
    user: AuthenticatedUser,
    is_admin: IsAdmin,
    db: DbSession,
    redis: RedisClient,
    cache: AudioCache,
) -> Response:
    """Synthesize audio for a block. Returns audio data directly with long-polling."""
    # Get or create credits for all users (including admins for tracking)
    user_credits = await get_or_create_user_credits(user.id, db)

    if is_admin and user_credits.balance < 1000:  # Auto top-up admin credits if running low (dev/self-host purposes)
        top_up_amount = 10000
        balance_before = user_credits.balance
        user_credits.balance += top_up_amount

        # Create transaction record for audit trail
        transaction = CreditTransaction(
            user_id=user.id,
            type=TransactionType.credit_bonus,
            status=TransactionStatus.completed,
            amount=top_up_amount,
            balance_before=balance_before,
            balance_after=user_credits.balance,
            description="Admin auto top-up",
        )
        db.add(transaction)

    await db.commit()

    if user_credits.balance <= 0:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Insufficient credits. Please purchase credits to continue.",
        )

    served_codec = model.native_codec  # TODO change to "opus" once workers transcode
    variant_hash = BlockVariant.get_hash(
        text=block.text,
        model_slug=model.slug,
        voice_slug=voice.slug,
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
            user_id=user.id,
            model_slug=model.slug,
            voice_slug=voice.slug,
            text=block.text,
            speed=body.speed,
            codec=served_codec,
        )
        await redis.lpush(get_queue_name(model.slug), job.model_dump_json())

    # Long-polling: wait for audio to appear in cache AND inflight to be cleared
    timeout = 60.0
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

from __future__ import annotations

import asyncio
import base64
import io
import logging
import pickle
import uuid
from decimal import Decimal

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlmodel import select

from yapit.contracts import TTS_INFLIGHT, SynthesisJob, SynthesisParameters, SynthesisResult, get_queue_name
from yapit.gateway.auth import authenticate
from yapit.gateway.cache import Cache
from yapit.gateway.deps import (
    AudioCache,
    AuthenticatedUser,
    AuthenticatedUserCredits,
    ClientProcessorDep,
    CurrentBlock,
    CurrentDoc,
    CurrentTTSModel,
    CurrentVoice,
    DbSession,
    RedisClient,
    SettingsDep,
    SynthesisJobDep,
    ensure_admin_credits,
)
from yapit.gateway.domain_models import Block, BlockVariant, TTSModel, Voice
from yapit.gateway.exceptions import InsufficientCreditsError

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["synthesis"])

# Max number of preceding blocks to use for voice context
CONTEXT_BUFFER_SIZE = 3


async def _build_context_tokens(
    db: "DbSession",
    cache: Cache,
    document_id: uuid.UUID,
    current_block_idx: int,
    model: TTSModel,
    voice: Voice,
    codec: str,
) -> str | None:
    """Build serialized context tokens from preceding blocks.

    Retrieves cached audio tokens from up to CONTEXT_BUFFER_SIZE preceding blocks
    and serializes them for the worker.
    """
    if current_block_idx == 0:
        return None

    # Query preceding blocks (ordered by idx, limited to buffer size)
    start_idx = max(0, current_block_idx - CONTEXT_BUFFER_SIZE)
    result = await db.exec(
        select(Block)
        .where(Block.document_id == document_id)
        .where(Block.idx >= start_idx)
        .where(Block.idx < current_block_idx)
        .order_by(Block.idx)
    )
    preceding_blocks = result.all()

    if not preceding_blocks:
        return None

    # Collect (text, tokens) tuples from cached variants
    context_items: list[tuple[str, np.ndarray]] = []
    for blk in preceding_blocks:
        variant_hash = BlockVariant.get_hash(
            text=blk.text,
            model_slug=model.slug,
            voice_slug=voice.slug,
            codec=codec,
            parameters=voice.parameters,
        )
        token_data = await cache.retrieve_data(f"{variant_hash}:tokens")
        if token_data is None:
            continue
        # token_data is bytes (UTF-8 encoded base64 string from np.save)
        b64_str = token_data.decode("utf-8")
        buffer = io.BytesIO(base64.b64decode(b64_str))
        arr = np.load(buffer, allow_pickle=False)
        context_items.append((blk.text, arr))

    if not context_items:
        return None

    # Serialize list of (text, array) tuples (matches deserialize_context_tokens in adapter)
    buffer = io.BytesIO()
    pickle.dump(context_items, buffer)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


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
    job_id: uuid.UUID | None = Query(None),
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

        # Build context tokens from preceding blocks (HIGGS only, for voice consistency)
        context_tokens = None
        if model.slug.startswith("higgs"):
            context_tokens = await _build_context_tokens(
                db=db,
                cache=cache,
                document_id=block.document_id,
                current_block_idx=block.idx,
                model=model,
                voice=voice,
                codec=served_codec,
            )

        job = SynthesisJob(
            job_id=job_id or uuid.uuid4(),
            variant_hash=variant_hash,
            user_id=user.id,
            synthesis_parameters=SynthesisParameters(
                model_slug=model.slug,
                voice_slug=voice.slug,
                text=block.text,
                kwargs=voice.parameters,
                codec=served_codec,
                context_tokens=context_tokens,
            ),
        )
        await redis.lpush(get_queue_name(model.slug), job.model_dump_json())

    # Long-polling: wait for audio to appear in cache AND inflight to be cleared
    timeout = settings.synthesis_polling_timeout_seconds
    poll_interval = 0.1
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


@router.post("/tts/submit/model/{model_slug}/job/{job_id}")
async def submit_job(
    _: SynthesisJobDep,
    result: SynthesisResult,
    processor: ClientProcessorDep,
):
    """Submit synthesis result from the client."""
    if not processor.submit_result(result):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Job already completed or result already submitted"
        )

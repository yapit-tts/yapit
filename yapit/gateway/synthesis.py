"""Core synthesis logic, decoupled from transport (WebSocket, REST)."""

import asyncio
import uuid
from dataclasses import dataclass
from typing import Literal

from loguru import logger
from redis.asyncio import Redis
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select

from yapit.contracts import (
    TTS_AUDIO_CACHE,
    TTS_INFLIGHT,
    TTS_JOB_INDEX,
    TTS_JOBS,
    TTS_PENDING,
    TTS_SUBSCRIBERS,
    SynthesisJob,
    SynthesisParameters,
    get_queue_name,
)
from yapit.gateway.cache import Cache
from yapit.gateway.domain_models import BlockVariant, TTSModel, UsageType, Voice
from yapit.gateway.exceptions import UsageLimitExceededError
from yapit.gateway.metrics import log_event
from yapit.gateway.usage import check_usage_limit
from yapit.workers.queue import QueueConfig, push_job


@dataclass
class CachedResult:
    status: Literal["cached"] = "cached"
    variant_hash: str = ""

    @property
    def audio_url(self) -> str:
        return f"/v1/audio/{self.variant_hash}"


@dataclass
class QueuedResult:
    status: Literal["queued"] = "queued"
    variant_hash: str = ""

    @property
    def audio_url(self) -> str:
        return f"/v1/audio/{self.variant_hash}"


@dataclass
class ErrorResult:
    status: Literal["error"] = "error"
    error: str = ""

    @property
    def audio_url(self) -> None:
        return None


SynthesisResult = CachedResult | QueuedResult | ErrorResult


async def request_synthesis(
    db,
    redis: Redis,
    cache: Cache,
    user_id: str,
    text: str,
    model: TTSModel,
    voice: Voice,
    billing_enabled: bool,
    document_id: uuid.UUID,
    block_idx: int,
    track_for_websocket: bool,
) -> SynthesisResult:
    """Request synthesis for a single piece of text.

    Args:
        track_for_websocket: If True, adds subscriber/pending tracking for WebSocket notifications and cursor-based eviction. Set False for REST polling.
    """
    variant_hash = BlockVariant.get_hash(
        text=text,
        model_slug=model.slug,
        voice_slug=voice.slug,
        parameters=voice.parameters,
    )

    variant = (await db.exec(select(BlockVariant).where(BlockVariant.hash == variant_hash))).first()
    in_redis = await redis.exists(TTS_AUDIO_CACHE.format(hash=variant_hash))
    is_cached = variant is not None and (in_redis or await cache.exists(variant_hash))

    if is_cached:
        await log_event(
            "cache_hit",
            variant_hash=variant_hash,
            model_slug=model.slug,
            voice_slug=voice.slug,
            user_id=user_id,
            document_id=str(document_id),
            block_idx=block_idx,
        )
        return CachedResult(variant_hash=variant_hash)

    usage_type = UsageType.server_kokoro if model.slug.startswith("kokoro") else UsageType.premium_voice
    block_chars = int(len(text) * model.usage_multiplier)
    try:
        await check_usage_limit(user_id, usage_type, block_chars, db, billing_enabled=billing_enabled)
    except UsageLimitExceededError as e:
        return ErrorResult(error=str(e))

    variant_hash = await _queue_job(
        db=db,
        redis=redis,
        user_id=user_id,
        text=text,
        model=model,
        voice=voice,
        variant_hash=variant_hash,
        variant=variant,
        document_id=document_id,
        block_idx=block_idx,
        track_for_websocket=track_for_websocket,
    )

    return QueuedResult(variant_hash=variant_hash)


async def _queue_job(
    db,
    redis: Redis,
    user_id: str,
    text: str,
    model: TTSModel,
    voice: Voice,
    variant_hash: str,
    variant: BlockVariant | None,
    document_id: uuid.UUID,
    block_idx: int,
    track_for_websocket: bool,
) -> str:
    """Queue a synthesis job. Returns variant_hash."""
    if variant is None:
        stmt = (
            pg_insert(BlockVariant)
            .values(
                hash=variant_hash,
                model_id=model.id,
                voice_id=voice.id,
            )
            .on_conflict_do_nothing(index_elements=["hash"])
        )
        await db.exec(stmt)
        await db.commit()

    if track_for_websocket:
        # Track this block as subscriber to be notified when synthesis completes
        subscriber_key = TTS_SUBSCRIBERS.format(hash=variant_hash)
        subscriber_entry = f"{user_id}:{document_id}:{block_idx}"
        await redis.sadd(subscriber_key, subscriber_entry)
        await redis.expire(subscriber_key, 600)

        pending_key = TTS_PENDING.format(user_id=user_id, document_id=document_id)
        await redis.sadd(pending_key, block_idx)
        await redis.expire(pending_key, 600)

    job_id = uuid.uuid4()
    job_id_str = str(job_id)

    # TTL is a safety net for orphaned keys; result_consumer DELETE is the normal cleanup path
    was_set = await redis.set(TTS_INFLIGHT.format(hash=variant_hash), job_id_str, ex=600, nx=True)
    if not was_set:
        return variant_hash

    job = SynthesisJob(
        job_id=job_id,
        variant_hash=variant_hash,
        user_id=user_id,
        document_id=document_id,
        block_idx=block_idx,
        model_slug=model.slug,
        voice_slug=voice.slug,
        usage_multiplier=model.usage_multiplier,
        synthesis_parameters=SynthesisParameters(
            model=model.slug,
            voice=voice.slug,
            text=text,
            kwargs=voice.parameters,
        ),
    )

    queue_name = get_queue_name(model.slug)
    index_key = f"{user_id}:{document_id}:{block_idx}" if track_for_websocket else None

    tts_config = QueueConfig(queue_name=queue_name, jobs_key=TTS_JOBS, job_index_key=TTS_JOB_INDEX)
    await push_job(redis, tts_config, job_id_str, job.model_dump_json().encode(), index_key=index_key)

    queue_depth = await redis.zcard(queue_name)
    await log_event(
        "synthesis_queued",
        variant_hash=variant_hash,
        model_slug=model.slug,
        voice_slug=voice.slug,
        text_length=len(text),
        user_id=user_id,
        document_id=str(document_id),
        block_idx=block_idx,
        queue_depth=queue_depth,
        queue_type="tts",
    )

    return variant_hash


async def synthesize_and_wait(
    db,
    redis: Redis,
    cache: Cache,
    user_id: str,
    text: str,
    model: TTSModel,
    voice: Voice,
    billing_enabled: bool,
    document_id: uuid.UUID,
    block_idx: int,
    timeout_seconds: float,
    poll_interval: float,
) -> SynthesisResult:
    """Request synthesis and poll until result is ready or timeout."""
    result = await request_synthesis(
        db=db,
        redis=redis,
        cache=cache,
        user_id=user_id,
        text=text,
        model=model,
        voice=voice,
        billing_enabled=billing_enabled,
        document_id=document_id,
        block_idx=block_idx,
        track_for_websocket=False,
    )

    if not isinstance(result, QueuedResult):
        return result

    variant_hash = result.variant_hash
    audio_key = TTS_AUDIO_CACHE.format(hash=variant_hash)
    elapsed = 0.0
    while elapsed < timeout_seconds:
        if await redis.exists(audio_key) or await cache.exists(variant_hash):
            return CachedResult(variant_hash=variant_hash)
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

    logger.bind(
        user_id=user_id,
        model_slug=model.slug,
        voice_slug=voice.slug,
        variant_hash=variant_hash,
        document_id=str(document_id),
    ).warning(f"Synthesis timed out after {timeout_seconds}s")
    return ErrorResult(error="Synthesis timed out")

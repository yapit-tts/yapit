"""Core synthesis logic, decoupled from transport (WebSocket, REST)."""

import asyncio
import uuid
from dataclasses import dataclass
from typing import Literal

from loguru import logger
from redis.asyncio import Redis
from sqlmodel import select

from yapit.contracts import (
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
    synthesis_mode: Literal["browser", "server"],
    billing_enabled: bool,
    document_id: uuid.UUID,
    block_idx: int,
    track_for_websocket: bool,
) -> SynthesisResult:
    """Request synthesis for a single piece of text.

    Args:
        track_for_websocket: If True, adds subscriber/pending tracking for WebSocket notifications and cursor-based eviction. Set False for REST polling.
    """
    served_codec = model.native_codec
    variant_hash = BlockVariant.get_hash(
        text=text,
        model_slug=model.slug,
        voice_slug=voice.slug,
        codec=served_codec,
        parameters=voice.parameters,
    )

    variant = (await db.exec(select(BlockVariant).where(BlockVariant.hash == variant_hash))).first()
    cached_data = await cache.retrieve_data(variant_hash)
    is_cached = cached_data is not None and variant is not None

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

    if synthesis_mode != "browser":
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
    served_codec = model.native_codec

    if variant is None:
        variant = BlockVariant(hash=variant_hash, model_id=model.id, voice_id=voice.id)
        db.add(variant)
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

    # Already processing - we're now subscribed and will be notified
    if await redis.exists(TTS_INFLIGHT.format(hash=variant_hash)):
        return variant_hash

    # TTL covers max time in system (queue wait + processing + retries) with buffer. Increase if visibility/overflow/retry timeouts are raised significantly.
    await redis.set(TTS_INFLIGHT.format(hash=variant_hash), 1, ex=200, nx=True)

    job = SynthesisJob(
        job_id=uuid.uuid4(),
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
            codec=served_codec,
        ),
    )

    job_id = str(job.job_id)
    queue_name = get_queue_name(model.slug)
    index_key = f"{user_id}:{document_id}:{block_idx}" if track_for_websocket else None

    tts_config = QueueConfig(queue_name=queue_name, jobs_key=TTS_JOBS, job_index_key=TTS_JOB_INDEX)
    await push_job(redis, tts_config, job_id, job.model_dump_json().encode(), index_key=index_key)

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
        synthesis_mode="server",
        billing_enabled=billing_enabled,
        document_id=document_id,
        block_idx=block_idx,
        track_for_websocket=False,
    )

    if not isinstance(result, QueuedResult):
        return result

    variant_hash = result.variant_hash
    elapsed = 0.0
    while elapsed < timeout_seconds:
        if await cache.exists(variant_hash):
            return CachedResult(variant_hash=variant_hash)
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

    logger.warning(f"Synthesis timed out for {model.slug}/{voice.slug} after {timeout_seconds}s")
    return ErrorResult(error="Synthesis timed out")

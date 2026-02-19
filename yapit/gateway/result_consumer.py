"""Hot path: consumes worker results, caches audio, notifies subscribers.

No Postgres. Billing and metadata updates are pushed to tts:billing
for the billing consumer to process asynchronously.
"""

import asyncio
import base64
import time
import uuid

from loguru import logger
from pydantic import BaseModel
from redis.asyncio import Redis

from yapit.contracts import (
    TTS_BILLING,
    TTS_INFLIGHT,
    TTS_PENDING,
    TTS_RESULTS,
    TTS_SUBSCRIBERS,
    WorkerResult,
    get_pubsub_channel,
)
from yapit.gateway.api.v1.ws import BlockStatus, WSBlockStatus
from yapit.gateway.cache import Cache
from yapit.gateway.metrics import log_error, log_event

_background_tasks: set[asyncio.Task] = set()


class BillingEvent(BaseModel):
    """Pushed to tts:billing after user notification. Contains everything
    the billing consumer needs for Postgres writes (BlockVariant update,
    usage recording, engagement stats).
    """

    variant_hash: str
    user_id: str
    model_slug: str
    voice_slug: str
    text_length: int
    usage_multiplier: float
    duration_ms: int | None
    document_id: str
    block_idx: int
    cache_ref: str | None


async def run_result_consumer(redis: Redis, cache: Cache) -> None:
    logger.info("Result consumer starting")

    while True:
        try:
            result = await redis.brpop(TTS_RESULTS, timeout=5)
            if result is None:
                continue

            _, result_json = result
            worker_result = WorkerResult.model_validate_json(result_json)
            task = asyncio.create_task(_process_result(redis, cache, worker_result))
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)

        except asyncio.CancelledError:
            logger.info("Result consumer shutting down")
            raise
        except Exception as e:
            logger.exception(f"Error in result consumer: {e}")
            await log_error(f"Result consumer loop error: {e}")
            await asyncio.sleep(1)


async def _process_result(redis: Redis, cache: Cache, result: WorkerResult) -> None:
    result_log = logger.bind(
        variant_hash=result.variant_hash,
        user_id=result.user_id,
        model_slug=result.model_slug,
        voice_slug=result.voice_slug,
        job_id=str(result.job_id),
        worker_id=result.worker_id,
    )
    try:
        if result.error:
            await _handle_error(redis, result)
        else:
            await _handle_success(redis, cache, result)
    except Exception as e:
        result_log.exception(f"Error processing result: {e}")
        await log_error(
            f"Result processing failed for variant {result.variant_hash}: {e}",
            variant_hash=result.variant_hash,
            model_slug=result.model_slug,
            voice_slug=result.voice_slug,
            user_id=result.user_id,
            document_id=str(result.document_id),
            block_idx=result.block_idx,
        )
        await _notify_subscribers(redis, result, status="error", error=f"Internal error: {e}")


async def _handle_success(redis: Redis, cache: Cache, result: WorkerResult) -> None:
    log = logger.bind(
        variant_hash=result.variant_hash,
        user_id=result.user_id,
        model_slug=result.model_slug,
        voice_slug=result.voice_slug,
        job_id=str(result.job_id),
        worker_id=result.worker_id,
    )

    inflight_key = TTS_INFLIGHT.format(hash=result.variant_hash)
    if await redis.delete(inflight_key) == 0:
        log.info("Variant already finalized, skipping duplicate result")
        return

    finalize_start = time.time()

    if not result.audio_base64:
        log.info("Empty audio, marking as skipped")
        await _notify_subscribers(redis, result, status="skipped")
        return

    audio = base64.b64decode(result.audio_base64)
    cache_ref = await cache.store(result.variant_hash, audio)

    await _notify_subscribers(
        redis,
        result,
        status="cached",
        audio_url=f"/v1/audio/{result.variant_hash}",
    )

    billing_event = BillingEvent(
        variant_hash=result.variant_hash,
        user_id=result.user_id,
        model_slug=result.model_slug,
        voice_slug=result.voice_slug,
        text_length=result.text_length,
        usage_multiplier=result.usage_multiplier,
        duration_ms=result.duration_ms,
        document_id=str(result.document_id),
        block_idx=result.block_idx,
        cache_ref=cache_ref,
    )
    await redis.lpush(TTS_BILLING, billing_event.model_dump_json())

    finalize_ms = int((time.time() - finalize_start) * 1000)

    await log_event(
        "synthesis_complete",
        variant_hash=result.variant_hash,
        model_slug=result.model_slug,
        voice_slug=result.voice_slug,
        text_length=result.text_length,
        queue_wait_ms=result.queue_wait_ms,
        worker_latency_ms=result.processing_time_ms,
        total_latency_ms=result.queue_wait_ms + result.processing_time_ms + finalize_ms,
        audio_duration_ms=result.duration_ms,
        worker_id=result.worker_id,
        queue_type="tts",
        user_id=result.user_id,
        document_id=str(result.document_id),
        block_idx=result.block_idx,
    )


async def _handle_error(redis: Redis, result: WorkerResult) -> None:
    log = logger.bind(
        variant_hash=result.variant_hash,
        user_id=result.user_id,
        model_slug=result.model_slug,
        voice_slug=result.voice_slug,
        job_id=str(result.job_id),
        worker_id=result.worker_id,
    )

    inflight_key = TTS_INFLIGHT.format(hash=result.variant_hash)
    if await redis.delete(inflight_key) == 0:
        log.info("Variant already finalized, skipping duplicate error result")
        return

    await log_event(
        "synthesis_error",
        variant_hash=result.variant_hash,
        model_slug=result.model_slug,
        voice_slug=result.voice_slug,
        queue_wait_ms=result.queue_wait_ms,
        worker_latency_ms=result.processing_time_ms,
        worker_id=result.worker_id,
        queue_type="tts",
        user_id=result.user_id,
        document_id=str(result.document_id),
        block_idx=result.block_idx,
        data={"error": result.error},
    )

    await _notify_subscribers(redis, result, status="error", error=result.error)


async def _notify_subscribers(
    redis: Redis,
    result: WorkerResult,
    status: BlockStatus,
    audio_url: str | None = None,
    error: str | None = None,
) -> None:
    subscriber_key = TTS_SUBSCRIBERS.format(hash=result.variant_hash)
    subscribers = await redis.smembers(subscriber_key)

    for entry in subscribers:
        parts = entry.decode().split(":")
        if len(parts) != 3:
            logger.bind(
                variant_hash=result.variant_hash,
                user_id=result.user_id,
                model_slug=result.model_slug,
                voice_slug=result.voice_slug,
            ).error(f"Invalid subscriber entry format: {entry}")
            continue

        user_id, doc_id_str, block_idx_str = parts
        doc_id = uuid.UUID(doc_id_str)
        block_idx = int(block_idx_str)

        pending_key = TTS_PENDING.format(user_id=user_id, document_id=doc_id)
        await redis.srem(pending_key, block_idx)

        await redis.publish(
            get_pubsub_channel(user_id, doc_id),
            WSBlockStatus(
                document_id=doc_id,
                block_idx=block_idx,
                status=status,
                audio_url=audio_url,
                error=error,
                model_slug=result.model_slug,
                voice_slug=result.voice_slug,
            ).model_dump_json(),
        )

    await redis.delete(subscriber_key)

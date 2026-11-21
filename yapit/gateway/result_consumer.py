"""Hot path: consumes worker results, buffers audio in Redis, notifies subscribers.

No Postgres, no SQLite. Audio is SET in Redis (sub-ms) for immediate serving,
then queued for batch persistence to SQLite via tts:persist.
Billing events are pushed to tts:billing for the billing consumer.
"""

import asyncio
import base64
import time
import uuid

from loguru import logger
from pydantic import BaseModel
from redis.asyncio import Redis

from yapit.contracts import (
    AUDIO_JOB_AWAITED,
    AUDIO_JOB_WAITERS,
    AUDIO_JOB_WAKE,
    TTS_AUDIO_CACHE,
    TTS_BILLING_STREAM,
    TTS_FINALIZED,
    TTS_FINALIZED_TTL_S,
    TTS_INFLIGHT,
    TTS_PENDING,
    TTS_PERSIST,
    TTS_RESULTS,
    TTS_SKIPPED,
    TTS_SKIPPED_TTL_S,
    TTS_SUBSCRIBERS,
    TTS_TIMESTAMPS_CACHE,
    WorkerResult,
    get_pubsub_channel,
)
from yapit.gateway.api.v1.ws import BlockStatus, WSBlockStatus
from yapit.gateway.backoff import Backoff
from yapit.gateway.metrics import log_error, log_event

AUDIO_CACHE_TTL_S = 300

_background_tasks: set[asyncio.Task] = set()


class BillingEvent(BaseModel):
    """Pushed to tts:billing:stream after user notification. Contains everything
    the billing consumer needs for Postgres writes (BlockVariant update,
    usage recording, engagement stats).
    """

    job_id: str
    variant_hash: str
    user_id: str
    model_slug: str
    voice_slug: str
    text_length: int
    usage_multiplier: float
    duration_ms: int | None
    document_id: str
    block_idx: int


async def run_result_consumer(redis: Redis) -> None:
    logger.info("Result consumer starting")

    backoff = Backoff()
    while True:
        try:
            result = await redis.brpop(TTS_RESULTS, timeout=5)
            if result is None:
                continue

            _, result_json = result
            worker_result = WorkerResult.model_validate_json(result_json)
            task = asyncio.create_task(_process_result(redis, worker_result))
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)

            backoff.reset()

        except asyncio.CancelledError:
            logger.info("Result consumer shutting down")
            raise
        except Exception as e:
            logger.exception(f"Error in result consumer: {e}")
            await log_error(f"Result consumer loop error: {e}")
            await backoff.sleep()


async def _process_result(redis: Redis, result: WorkerResult) -> None:
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
            await _handle_success(redis, result)
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
        await _notify_subscribers(redis, result, status="error", error="Synthesis failed")


async def _handle_success(redis: Redis, result: WorkerResult) -> None:
    log = logger.bind(
        variant_hash=result.variant_hash,
        user_id=result.user_id,
        model_slug=result.model_slug,
        voice_slug=result.voice_slug,
        job_id=str(result.job_id),
        worker_id=result.worker_id,
    )

    finalize_start = time.time()

    if not result.audio_base64:
        log.info("Empty audio, marking as skipped")
        await redis.set(TTS_SKIPPED.format(hash=result.variant_hash), 1, ex=TTS_SKIPPED_TTL_S)
        await _release_inflight(redis, result)
        await _notify_subscribers(redis, result, status="skipped")
        await _wake_audio_jobs(redis, result.variant_hash)
        return

    # The first result to arrive finalizes the variant: it alone is stored, billed and persisted.
    if not await redis.eval(
        _FINALIZE, 1, TTS_FINALIZED.format(hash=result.variant_hash), str(result.job_id), TTS_FINALIZED_TTL_S
    ):
        log.info("Variant already finalized, skipping duplicate result")
        await _release_inflight(redis, result)
        return

    audio = base64.b64decode(result.audio_base64)
    await redis.set(TTS_AUDIO_CACHE.format(hash=result.variant_hash), audio, ex=AUDIO_CACHE_TTL_S)

    if result.word_timestamps_json:
        ts_key = TTS_TIMESTAMPS_CACHE.format(hash=result.variant_hash)
        await redis.set(ts_key, result.word_timestamps_json.encode(), ex=AUDIO_CACHE_TTL_S)

    await _release_inflight(redis, result)

    await _notify_subscribers(
        redis,
        result,
        status="cached",
        audio_url=f"/v1/audio/{result.variant_hash}",
        word_timestamps=result.word_timestamps_json,
    )

    billing_event = BillingEvent(
        job_id=str(result.job_id),
        variant_hash=result.variant_hash,
        user_id=result.user_id,
        model_slug=result.model_slug,
        voice_slug=result.voice_slug,
        text_length=result.text_length,
        usage_multiplier=result.usage_multiplier,
        duration_ms=result.duration_ms,
        document_id=str(result.document_id),
        block_idx=result.block_idx,
    )
    await redis.xadd(TTS_BILLING_STREAM, {"data": billing_event.model_dump_json()})
    await redis.lpush(TTS_PERSIST, result.variant_hash)
    await _wake_audio_jobs(redis, result.variant_hash)

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
        data={"finalize_ms": finalize_ms},
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

    finalized = await redis.get(TTS_FINALIZED.format(hash=result.variant_hash))
    if finalized is not None and finalized.decode() != f"open:{result.job_id}":
        log.info("Variant already finalized, skipping duplicate error result")
        return
    if await _release_inflight(redis, result):
        log.info("Another job for this variant is in flight, leaving the error to it")
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
        data={"error": result.error, "error_detail": result.error_detail},
    )

    await _notify_subscribers(redis, result, status="error", error=result.error)
    await _wake_audio_jobs(redis, result.variant_hash)


async def _wake_audio_jobs(redis: Redis, variant_hash: str) -> None:
    """Tell the audio job feeder that every job awaiting this variant has room for another block."""
    waiters_key = AUDIO_JOB_WAITERS.format(hash=variant_hash)
    async with redis.pipeline(transaction=True) as pipe:
        pipe.smembers(waiters_key)
        pipe.delete(waiters_key)
        waiters, _ = await pipe.execute()
    for waiter in waiters:
        user_id, job_id = waiter.decode().rsplit(":", 1)
        await redis.hdel(AUDIO_JOB_AWAITED.format(job_id=job_id), variant_hash)
        await redis.lpush(AUDIO_JOB_WAKE, user_id)


# Claims the variant for this result's job unless another job's result finalized it first.
_FINALIZE = """
local finalized = redis.call('GET', KEYS[1])
if finalized and finalized ~= 'open:' .. ARGV[1] then
    return 0
end
redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
return 1
"""


# Deletes the in-flight marker only when this result's job holds it: a marker can expire while its
# job waits, and the next request for the variant then holds a marker of its own. Returns 1 when
# another job holds it.
_RELEASE_INFLIGHT = """
local owner = redis.call('GET', KEYS[1])
if owner == ARGV[1] then
    redis.call('DEL', KEYS[1])
    return 0
end
if owner then
    return 1
end
return 0
"""


async def _release_inflight(redis: Redis, result: WorkerResult) -> bool:
    """Release this result's marker; True if another job for the variant holds the marker instead."""
    inflight_key = TTS_INFLIGHT.format(hash=result.variant_hash)
    return bool(await redis.eval(_RELEASE_INFLIGHT, 1, inflight_key, str(result.job_id)))


async def _notify_subscribers(
    redis: Redis,
    result: WorkerResult,
    status: BlockStatus,
    audio_url: str | None = None,
    error: str | None = None,
    word_timestamps: str | None = None,
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
                word_timestamps=word_timestamps,
                duration_ms=result.duration_ms,
            ).model_dump_json(),
        )

    await redis.delete(subscriber_key)

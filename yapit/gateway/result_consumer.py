"""Consumes results from workers and finalizes synthesis."""

import asyncio
import base64
import time
import uuid

from loguru import logger
from redis.asyncio import Redis
from sqlmodel import col, update

from yapit.contracts import (
    TTS_INFLIGHT,
    TTS_PENDING,
    TTS_RESULTS,
    TTS_SUBSCRIBERS,
    WorkerResult,
    get_pubsub_channel,
)
from yapit.gateway.api.v1.ws import BlockStatus, WSBlockStatus
from yapit.gateway.cache import Cache
from yapit.gateway.config import Settings
from yapit.gateway.db import create_session
from yapit.gateway.domain_models import BlockVariant, UsageType
from yapit.gateway.metrics import log_error, log_event
from yapit.gateway.usage import record_usage


async def run_result_consumer(redis: Redis, cache: Cache, settings: Settings) -> None:
    logger.info("Result consumer starting")

    while True:
        try:
            result = await redis.brpop(TTS_RESULTS, timeout=5)
            if result is None:
                continue

            _, result_json = result
            worker_result = WorkerResult.model_validate_json(result_json)
            asyncio.create_task(_process_result(redis, cache, worker_result, settings))

        except asyncio.CancelledError:
            logger.info("Result consumer shutting down")
            raise
        except Exception as e:
            logger.exception(f"Error in result consumer: {e}")
            await asyncio.sleep(1)


async def _process_result(redis: Redis, cache: Cache, result: WorkerResult, settings: Settings) -> None:
    try:
        if result.error:
            await _handle_error(redis, result, settings)
        else:
            await _handle_success(redis, cache, result, settings)
    except Exception as e:
        logger.exception(f"Error processing result for variant {result.variant_hash}: {e}")
        await log_error(
            f"Result processing failed for variant {result.variant_hash}: {e}",
            variant_hash=result.variant_hash,
            model_slug=result.model_slug,
            voice_slug=result.voice_slug,
            user_id=result.user_id,
            document_id=str(result.document_id),
            block_idx=result.block_idx,
        )
        # Notify subscribers so frontend isn't stuck waiting forever
        await _notify_subscribers(redis, result, status="error", error=f"Internal error: {e}")


async def _handle_success(
    redis: Redis,
    cache: Cache,
    result: WorkerResult,
    settings: Settings,
) -> None:
    # Atomically claim this result - prevents double-processing if job was requeued
    # and both workers completed. First to delete wins, others skip.
    inflight_key = TTS_INFLIGHT.format(hash=result.variant_hash)
    if await redis.delete(inflight_key) == 0:
        logger.info(f"Variant {result.variant_hash} already finalized, skipping duplicate result")
        return

    finalize_start = time.time()

    if not result.audio_base64:
        logger.info(f"Empty audio for variant {result.variant_hash}, marking as skipped")
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

    async for db in create_session(settings):
        await db.exec(
            update(BlockVariant)
            .where(col(BlockVariant.hash) == result.variant_hash)
            .values(duration_ms=result.duration_ms, cache_ref=cache_ref)
        )

        usage_type = UsageType.server_kokoro if result.model_slug.startswith("kokoro") else UsageType.premium_voice
        characters_used = int(result.text_length * result.usage_multiplier)

        await record_usage(
            user_id=result.user_id,
            usage_type=usage_type,
            amount=characters_used,
            db=db,
            reference_id=result.variant_hash,
            description=f"TTS synthesis: {result.text_length} chars ({result.model_slug})",
            details={
                "variant_hash": result.variant_hash,
                "model_slug": result.model_slug,
                "duration_ms": result.duration_ms,
                "usage_multiplier": result.usage_multiplier,
            },
        )
        break

    finalize_time_ms = int((time.time() - finalize_start) * 1000)

    await log_event(
        "synthesis_complete",
        variant_hash=result.variant_hash,
        model_slug=result.model_slug,
        voice_slug=result.voice_slug,
        text_length=result.text_length,
        queue_wait_ms=result.queue_wait_ms,
        worker_latency_ms=result.processing_time_ms,
        total_latency_ms=result.queue_wait_ms + result.processing_time_ms + finalize_time_ms,
        audio_duration_ms=result.duration_ms,
        worker_id=result.worker_id,
        queue_type="tts",
        user_id=result.user_id,
        document_id=str(result.document_id),
        block_idx=result.block_idx,
    )


async def _handle_error(redis: Redis, result: WorkerResult, settings: Settings) -> None:
    # Atomically claim this result - same dedup logic as _handle_success
    inflight_key = TTS_INFLIGHT.format(hash=result.variant_hash)
    if await redis.delete(inflight_key) == 0:
        logger.info(f"Variant {result.variant_hash} already finalized, skipping duplicate error result")
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
            logger.error(f"Invalid subscriber entry format: {entry}")
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

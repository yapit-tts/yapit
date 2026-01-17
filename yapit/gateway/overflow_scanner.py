"""Scans for stale jobs and sends them to RunPod overflow."""

import asyncio
import base64
import time

from loguru import logger
from redis.asyncio import Redis

from yapit.contracts import (
    TTS_JOB_INDEX,
    TTS_JOBS,
    TTS_QUEUE,
    TTS_RESULTS,
    SynthesisJob,
    WorkerResult,
)
from yapit.gateway.config import Settings

OVERFLOW_THRESHOLD_S = 30
SCAN_INTERVAL_S = 5


async def run_overflow_scanner(redis: Redis, settings: Settings) -> None:
    if not settings.runpod_api_key:
        logger.warning("No RunPod API key configured, overflow scanner disabled")
        return

    import runpod

    runpod.api_key = settings.runpod_api_key

    overflow_config = _get_overflow_config(settings)
    if not overflow_config:
        logger.warning("No overflow endpoints configured, overflow scanner disabled")
        return

    logger.info(f"Overflow scanner starting, models={list(overflow_config.keys())}")

    while True:
        try:
            for model, endpoint_id in overflow_config.items():
                await _check_queue_for_overflow(redis, model, endpoint_id, settings)
            await asyncio.sleep(SCAN_INTERVAL_S)
        except asyncio.CancelledError:
            logger.info("Overflow scanner shutting down")
            raise
        except Exception as e:
            logger.exception(f"Error in overflow scanner: {e}")
            await asyncio.sleep(SCAN_INTERVAL_S)


def _get_overflow_config(settings: Settings) -> dict[str, str]:
    """Returns {model_slug: runpod_endpoint_id} for models with overflow."""
    # TODO: Make this configurable via settings or database
    # For now, hardcode kokoro -> runpod endpoint
    # TODO we said it'ss fine to hardcode bcs since if we change either kokoro or runpod we're gonna have to refactor "substantially" anyways, but like the setting is missing from settings + env var. and should it maybe be called kokoro_runpod_overflow_endpoint_id or sth?
    if settings.kokoro_overflow_endpoint_id:
        return {"kokoro": settings.kokoro_overflow_endpoint_id}
    return {}


async def _check_queue_for_overflow(
    redis: Redis,
    model: str,
    endpoint_id: str,
    settings: Settings,
) -> None:
    queue_name = TTS_QUEUE.format(model=model)

    # Get oldest job_id without removing (ZRANGE returns [(member, score), ...])
    oldest = await redis.zrange(queue_name, 0, 0, withscores=True)
    if not oldest:
        return

    job_id_bytes, queued_score = oldest[0]
    job_id = job_id_bytes.decode() if isinstance(job_id_bytes, bytes) else job_id_bytes

    age = time.time() - queued_score
    if age < OVERFLOW_THRESHOLD_S:
        return

    # Job is stale, try to claim it
    removed = await redis.zrem(queue_name, job_id)
    if not removed:
        return  # Worker grabbed it first

    job_json = await redis.hget(TTS_JOBS, job_id)
    if job_json is None:
        return  # Already processed or evicted

    await redis.hdel(TTS_JOBS, job_id)

    job = SynthesisJob.model_validate_json(job_json)

    # Clean up job index
    index_key = f"{job.user_id}:{job.document_id}:{job.block_idx}"
    await redis.hdel(TTS_JOB_INDEX, index_key)

    logger.info(f"Overflow: job {job_id} stale for {age:.1f}s, sending to RunPod")

    await _process_via_runpod(redis, job, endpoint_id, settings)


async def _process_via_runpod(
    redis: Redis,
    job: SynthesisJob,
    endpoint_id: str,
    settings: Settings,
) -> None:
    import runpod

    start_time = time.time()
    endpoint = runpod.Endpoint(endpoint_id)

    try:
        result = await asyncio.to_thread(
            endpoint.run_sync,
            job.synthesis_parameters.model_dump(),
            timeout=settings.runpod_request_timeout_seconds,
        )

        if "error" in result:
            raise RuntimeError(f"RunPod error: {result['error']}")

        processing_time_ms = int((time.time() - start_time) * 1000)
        audio = base64.b64decode(result["audio_base64"])

        worker_result = WorkerResult(
            job_id=job.job_id,
            variant_hash=job.variant_hash,
            user_id=job.user_id,
            document_id=job.document_id,
            block_idx=job.block_idx,
            model_slug=job.model_slug,
            voice_slug=job.voice_slug,
            text_length=len(job.synthesis_parameters.text),
            worker_id="overflow-runpod",
            processing_time_ms=processing_time_ms,
            audio=audio,
            duration_ms=result["duration_ms"],
            audio_tokens=result.get("audio_tokens"),
        )

        logger.info(f"Overflow job {job.job_id} completed: {processing_time_ms}ms, {result['duration_ms']}ms audio")

    except Exception as e:
        processing_time_ms = int((time.time() - start_time) * 1000)
        logger.exception(f"Overflow job {job.job_id} failed: {e}")

        worker_result = WorkerResult(
            job_id=job.job_id,
            variant_hash=job.variant_hash,
            user_id=job.user_id,
            document_id=job.document_id,
            block_idx=job.block_idx,
            model_slug=job.model_slug,
            voice_slug=job.voice_slug,
            text_length=len(job.synthesis_parameters.text),
            worker_id="overflow-runpod",
            processing_time_ms=processing_time_ms,
            error=str(e),
        )

    await redis.lpush(TTS_RESULTS, worker_result.model_dump_json())

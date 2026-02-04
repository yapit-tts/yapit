"""Scans for stale jobs and sends them to RunPod overflow."""

import asyncio
import json
import time

from loguru import logger
from redis.asyncio import Redis

from yapit.contracts import parse_queue_name
from yapit.gateway.config import Settings
from yapit.gateway.metrics import log_event


async def run_overflow_scanner(
    redis: Redis,
    settings: Settings,
    queue_name: str,
    jobs_key: str,
    job_index_key: str | None,
    endpoint_id: str,
    result_key_pattern: str,
    overflow_threshold_s: int,
    scan_interval_s: int,
    name: str,
) -> None:
    """Run overflow scanner for a queue.

    Args:
        redis: Redis client
        settings: App settings (for RunPod timeout)
        queue_name: Sorted set queue to scan
        jobs_key: Hash where jobs are stored
        job_index_key: Optional hash for job index cleanup
        endpoint_id: RunPod endpoint ID
        result_key_pattern: Where to push results. Can contain {job_id} for substitution.
        overflow_threshold_s: Seconds before a job is sent to overflow
        scan_interval_s: Seconds between scans
        name: Name for logging
    """
    if not settings.runpod_api_key or not settings.runpod_request_timeout_seconds:
        logger.warning(f"{name} scanner disabled: missing RunPod API key or timeout config")
        return

    import runpod

    runpod.api_key = settings.runpod_api_key
    runpod_timeout = settings.runpod_request_timeout_seconds

    logger.info(f"{name} scanner starting (queue={queue_name}, threshold={overflow_threshold_s}s)")

    while True:
        try:
            await _check_queue_for_overflow(
                redis,
                runpod_timeout,
                queue_name,
                jobs_key,
                job_index_key,
                endpoint_id,
                result_key_pattern,
                overflow_threshold_s,
                name,
            )
            await asyncio.sleep(scan_interval_s)
        except asyncio.CancelledError:
            logger.info(f"{name} scanner shutting down")
            raise
        except Exception as e:
            logger.exception(f"Error in {name} scanner: {e}")
            await asyncio.sleep(scan_interval_s)


async def _check_queue_for_overflow(
    redis: Redis,
    runpod_timeout: int,
    queue_name: str,
    jobs_key: str,
    job_index_key: str | None,
    endpoint_id: str,
    result_key_pattern: str,
    overflow_threshold_s: int,
    name: str,
) -> None:
    oldest = await redis.zrange(queue_name, 0, 0, withscores=True)
    if not oldest:
        return

    job_id_bytes, queued_score = oldest[0]
    job_id = job_id_bytes.decode() if isinstance(job_id_bytes, bytes) else job_id_bytes

    age = time.time() - queued_score
    if age < overflow_threshold_s:
        return

    # Claim the job
    removed = await redis.zrem(queue_name, job_id)
    if not removed:
        return  # Worker grabbed it first

    wrapper_json = await redis.hget(jobs_key, job_id)
    if wrapper_json is None:
        return  # Already processed or evicted

    await redis.hdel(jobs_key, job_id)

    wrapper = json.loads(wrapper_json)
    raw_job = wrapper["job"]

    # Clean up job index if present (index_key stored in wrapper by push_job)
    if job_index_key and "index_key" in wrapper:
        await redis.hdel(job_index_key, wrapper["index_key"])

    queue_type, model_slug = parse_queue_name(queue_name)
    queue_wait_ms = int(age * 1000)

    logger.info(f"{name}: job {job_id} stale for {age:.1f}s, sending to RunPod")

    await log_event(
        "job_overflow",
        queue_type=queue_type,
        model_slug=model_slug,
        queue_wait_ms=queue_wait_ms,
        data={"job_id": job_id},
    )

    result_key = result_key_pattern.format(job_id=job_id)
    await _process_via_runpod(
        redis,
        job_id,
        raw_job,
        endpoint_id,
        result_key,
        runpod_timeout,
        name,
        queue_type,
        model_slug,
        queue_wait_ms,
    )


async def _process_via_runpod(
    redis: Redis,
    job_id: str,
    raw_job: str,
    endpoint_id: str,
    result_key: str,
    runpod_timeout: int,
    name: str,
    queue_type: str,
    model_slug: str | None,
    queue_wait_ms: int,
) -> None:
    import runpod

    start_time = time.time()
    endpoint = runpod.Endpoint(endpoint_id)
    job_data = json.loads(raw_job)
    worker_id = f"{name}-runpod"

    try:
        runpod_result = await asyncio.to_thread(
            endpoint.run_sync,
            job_data,
            timeout=runpod_timeout,
        )

        if runpod_result is None:
            raise RuntimeError("RunPod returned None (job FAILED — check RunPod dashboard for logs)")
        if isinstance(runpod_result, dict) and "error" in runpod_result:
            raise RuntimeError(f"RunPod error: {runpod_result['error']}")

        processing_time_ms = int((time.time() - start_time) * 1000)
        logger.info(f"{name} job {job_id} completed in {processing_time_ms}ms")

        await log_event(
            "overflow_complete",
            queue_type=queue_type,
            model_slug=model_slug,
            worker_latency_ms=processing_time_ms,
            worker_id=worker_id,
            data={"job_id": job_id},
        )

        # Handler returns a result-consumer-compatible dict; add runtime fields
        runpod_result["job_id"] = job_id
        runpod_result["worker_id"] = worker_id
        runpod_result["processing_time_ms"] = processing_time_ms
        runpod_result["queue_wait_ms"] = queue_wait_ms
        await redis.lpush(result_key, json.dumps(runpod_result))

    except Exception as e:
        processing_time_ms = int((time.time() - start_time) * 1000)
        logger.exception(f"{name} job {job_id} failed: {e}")

        await log_event(
            "overflow_error",
            queue_type=queue_type,
            model_slug=model_slug,
            worker_latency_ms=processing_time_ms,
            worker_id=worker_id,
            data={"job_id": job_id, "error": str(e)},
        )

        error_result = _build_error_result(
            queue_type, job_id, job_data, worker_id, processing_time_ms, queue_wait_ms, str(e)
        )
        await redis.lpush(result_key, json.dumps(error_result))


def _build_error_result(
    queue_type: str,
    job_id: str,
    job_data: dict,
    worker_id: str,
    processing_time_ms: int,
    queue_wait_ms: int,
    error: str,
) -> dict:
    """Build an error result compatible with the queue's result consumer."""
    base: dict = {
        "job_id": job_id,
        "worker_id": worker_id,
        "processing_time_ms": processing_time_ms,
        "error": error,
    }
    if queue_type == "tts":
        base["variant_hash"] = job_data["variant_hash"]
        base["user_id"] = job_data["user_id"]
        base["document_id"] = job_data["document_id"]
        base["block_idx"] = job_data["block_idx"]
        base["model_slug"] = job_data["model_slug"]
        base["voice_slug"] = job_data["voice_slug"]
        base["text_length"] = len(job_data["synthesis_parameters"]["text"])
        base["usage_multiplier"] = job_data["usage_multiplier"]
        base["queue_wait_ms"] = queue_wait_ms
    elif queue_type == "yolo":
        base["figures"] = []
        base["page_width"] = None
        base["page_height"] = None
    return base

"""Scans for stuck jobs and re-queues or moves to DLQ.

Generic scanner that works for both TTS and YOLO queues.
Processing entries store queue_name and dlq_key so scanner doesn't need to parse job types.
"""

import asyncio
import json
import time
import uuid

from loguru import logger
from redis.asyncio import Redis

from yapit.contracts import YOLO_RESULT, YoloResult, parse_queue_name
from yapit.gateway.metrics import log_event
from yapit.workers.queue import move_to_dlq, requeue_job


async def run_visibility_scanner(
    redis: Redis,
    processing_pattern: str,
    jobs_key: str,
    visibility_timeout_s: int,
    max_retries: int,
    scan_interval_s: int,
    name: str = "visibility",
) -> None:
    """Run visibility timeout scanner for a queue type.

    Args:
        redis: Redis client
        processing_pattern: Pattern to match processing keys, e.g. "tts:processing:*"
        jobs_key: Hash key where jobs are stored, e.g. "tts:jobs"
        visibility_timeout_s: Seconds before a job is considered stuck
        max_retries: Max retries before moving to DLQ
        scan_interval_s: Seconds between scans
        name: Name for logging
    """
    logger.info(f"{name} scanner starting (pattern={processing_pattern}, timeout={visibility_timeout_s}s)")

    while True:
        try:
            await _scan_processing_sets(redis, processing_pattern, jobs_key, visibility_timeout_s, max_retries)
            await asyncio.sleep(scan_interval_s)
        except asyncio.CancelledError:
            logger.info(f"{name} scanner shutting down")
            raise
        except Exception as e:
            logger.exception(f"Error in {name} scanner: {e}")
            await asyncio.sleep(scan_interval_s)


async def _scan_processing_sets(
    redis: Redis,
    processing_pattern: str,
    jobs_key: str,
    visibility_timeout_s: int,
    max_retries: int,
) -> None:
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor, match=processing_pattern, count=100)
        for key in keys:
            await _check_processing_set(redis, key, jobs_key, visibility_timeout_s, max_retries)
        if cursor == 0:
            break


async def _check_processing_set(
    redis: Redis,
    processing_key: bytes,
    jobs_key: str,
    visibility_timeout_s: int,
    max_retries: int,
) -> None:
    entries = await redis.hgetall(processing_key)
    now = time.time()

    for job_id_bytes, entry_json in entries.items():
        entry = json.loads(entry_json)

        age = now - entry["processing_started"]
        if age < visibility_timeout_s:
            continue

        job_id = job_id_bytes.decode() if isinstance(job_id_bytes, bytes) else job_id_bytes
        retry_count = entry["retry_count"]
        raw_job = entry["job"].encode()
        queue_name = entry["queue_name"]
        dlq_key = entry["dlq_key"]

        logger.warning(f"Job {job_id} stuck for {age:.1f}s, retry_count={retry_count}")

        await redis.hdel(processing_key, job_id_bytes)

        queue_type, model_slug = parse_queue_name(queue_name)

        if retry_count >= max_retries:
            await move_to_dlq(redis, dlq_key, job_id, raw_job, retry_count)

            # For YOLO jobs, write error result so gateway doesn't wait for timeout
            if queue_type == "yolo":
                error_result = YoloResult(
                    job_id=uuid.UUID(job_id),
                    figures=[],
                    page_width=None,
                    page_height=None,
                    worker_id="dlq",
                    processing_time_ms=0,
                    error=f"Job moved to DLQ after {retry_count} retries",
                )
                result_key = YOLO_RESULT.format(job_id=job_id)
                await redis.lpush(result_key, error_result.model_dump_json())
                await redis.expire(result_key, 300)

            await log_event(
                "job_dlq",
                queue_type=queue_type,
                model_slug=model_slug,
                retry_count=retry_count,
                data={"job_id": job_id, "stuck_seconds": age},
            )
        else:
            await requeue_job(redis, queue_name, jobs_key, job_id, raw_job, retry_count)
            await log_event(
                "job_requeued",
                queue_type=queue_type,
                model_slug=model_slug,
                retry_count=retry_count + 1,
                data={"job_id": job_id, "stuck_seconds": age},
            )

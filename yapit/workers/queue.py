"""Shared queue utilities for pull-based workers.

Both TTS and YOLO workers use these functions for common Redis operations.
Job types and processing logic are handled by the workers themselves.
"""

import json
import time
from dataclasses import dataclass

import redis.asyncio as redis
from loguru import logger


@dataclass
class QueueConfig:
    """Configuration for a job queue."""

    queue_name: str  # sorted set: job_id -> timestamp
    jobs_key: str  # hash: job_id -> {retry_count, job}
    processing_pattern: str | None = None  # e.g. "tts:processing:{worker_id}" (only needed for workers)
    results_key: str | None = None  # list for result queue (TTS), None for direct key storage (YOLO)
    job_index_key: str | None = None  # hash for deduplication index (TTS only)


@dataclass
class PulledJob:
    """A job pulled from the queue."""

    job_id: str
    raw_job: bytes
    retry_count: int
    queued_at: float


async def push_job(
    client: redis.Redis,
    config: QueueConfig,
    job_id: str,
    raw_job: bytes,
    retry_count: int = 0,
    index_key: str | None = None,
) -> None:
    """Push a job to the queue.

    Args:
        client: Redis client
        config: Queue configuration
        job_id: Unique job identifier
        raw_job: Serialized job data (caller handles serialization)
        retry_count: Number of times this job has been retried
        index_key: Optional key for job index (for deduplication/eviction)
    """
    now = time.time()
    wrapper_data: dict = {"retry_count": retry_count, "job": raw_job.decode(), "queued_at": now}
    if index_key:
        wrapper_data["index_key"] = index_key
    job_wrapper = json.dumps(wrapper_data)

    await client.hset(config.jobs_key, job_id, job_wrapper)
    if index_key and config.job_index_key:
        await client.hset(config.job_index_key, index_key, job_id)
    await client.zadd(config.queue_name, {job_id: now})


async def pull_job(
    client: redis.Redis,
    config: QueueConfig,
    timeout: float = 5.0,
) -> PulledJob | None:
    """Pull a job from the queue.

    Uses BZPOPMIN for atomic pop from sorted set, then fetches job data from hash.

    Returns:
        PulledJob with job_id, raw_job bytes, retry_count, and queued_at timestamp.
        None if no job available within timeout.
    """
    result = await client.bzpopmin(config.queue_name, timeout=timeout)
    if result is None:
        return None

    _, job_id_bytes, _ = result
    job_id = job_id_bytes.decode() if isinstance(job_id_bytes, bytes) else job_id_bytes

    wrapper_json = await client.hget(config.jobs_key, job_id)
    if wrapper_json is None:
        # Job was evicted before we could process it
        logger.debug(f"Job {job_id} evicted before processing")
        return None

    await client.hdel(config.jobs_key, job_id)

    wrapper = json.loads(wrapper_json)
    return PulledJob(
        job_id=job_id,
        raw_job=wrapper["job"].encode(),
        retry_count=wrapper["retry_count"],
        queued_at=wrapper.get("queued_at", time.time()),
    )


async def track_processing(
    client: redis.Redis,
    processing_key: str,
    job_id: str,
    raw_job: bytes,
    retry_count: int,
    queue_name: str,
    dlq_key: str,
) -> None:
    """Track a job as being processed.

    Stores processing entry with timestamp for visibility timeout scanning.
    Includes queue_name and dlq_key so scanner can requeue without parsing job.
    """
    entry = json.dumps(
        {
            "processing_started": time.time(),
            "retry_count": retry_count,
            "job": raw_job.decode(),
            "queue_name": queue_name,
            "dlq_key": dlq_key,
        }
    )
    await client.hset(processing_key, job_id, entry)


async def requeue_job(
    client: redis.Redis,
    queue_name: str,
    jobs_key: str,
    job_id: str,
    raw_job: bytes,
    retry_count: int,
) -> None:
    """Requeue a job with incremented retry count.

    Called by visibility scanner when a job times out.
    """
    new_retry_count = retry_count + 1
    now = time.time()
    job_wrapper = json.dumps({"retry_count": new_retry_count, "job": raw_job.decode(), "queued_at": now})

    await client.hset(jobs_key, job_id, job_wrapper)
    await client.zadd(queue_name, {job_id: now})
    logger.info(f"Re-queued job {job_id}, retry_count={new_retry_count}")


DLQ_TTL_SECONDS = 7 * 24 * 3600  # 7 days


async def move_to_dlq(
    client: redis.Redis,
    dlq_key: str,
    job_id: str,
    raw_job: bytes,
    retry_count: int,
) -> None:
    """Move a job to the dead letter queue.

    DLQ expires 7 days after the last entry — preserves evidence for investigation
    while preventing unbounded growth from systematic failures.
    """
    entry = json.dumps(
        {
            "job_id": job_id,
            "job": raw_job.decode(),
            "retry_count": retry_count,
            "moved_at": time.time(),
        }
    )
    await client.lpush(dlq_key, entry)
    await client.expire(dlq_key, DLQ_TTL_SECONDS)
    logger.error(f"Job {job_id} moved to DLQ after {retry_count} retries")

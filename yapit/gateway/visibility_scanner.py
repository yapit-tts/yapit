"""Scans for stuck jobs and re-queues or moves to DLQ."""

import asyncio
import time

from loguru import logger
from redis.asyncio import Redis

from yapit.contracts import (
    TTS_DLQ,
    TTS_JOBS,
    TTS_QUEUE,
    ProcessingEntry,
    SynthesisJob,
)

VISIBILITY_TIMEOUT_S = 30
MAX_RETRIES = 3
SCAN_INTERVAL_S = 15


async def run_visibility_scanner(redis: Redis) -> None:
    logger.info("Visibility timeout scanner starting")

    while True:
        try:
            await _scan_processing_sets(redis)
            await asyncio.sleep(SCAN_INTERVAL_S)
        except asyncio.CancelledError:
            logger.info("Visibility scanner shutting down")
            raise
        except Exception as e:
            logger.exception(f"Error in visibility scanner: {e}")
            await asyncio.sleep(SCAN_INTERVAL_S)


async def _scan_processing_sets(redis: Redis) -> None:
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor, match="tts:processing:*", count=100)
        for key in keys:
            await _check_processing_set(redis, key)
        if cursor == 0:
            break


async def _check_processing_set(redis: Redis, processing_key: bytes) -> None:
    entries = await redis.hgetall(processing_key)
    now = time.time()

    for job_id, entry_json in entries.items():
        entry = ProcessingEntry.model_validate_json(entry_json)
        job = entry.job

        age = now - entry.processing_started
        if age < VISIBILITY_TIMEOUT_S:
            continue

        job_id_str = job_id.decode() if isinstance(job_id, bytes) else job_id
        logger.warning(f"Job {job_id_str} stuck for {age:.1f}s, retry_count={job.retry_count}")

        await redis.hdel(processing_key, job_id)

        if job.retry_count >= MAX_RETRIES:
            await _move_to_dlq(redis, job)
        else:
            await _requeue_job(redis, job)


async def _requeue_job(redis: Redis, job: SynthesisJob) -> None:
    new_job = SynthesisJob(
        job_id=job.job_id,
        variant_hash=job.variant_hash,
        user_id=job.user_id,
        document_id=job.document_id,
        block_idx=job.block_idx,
        model_slug=job.model_slug,
        voice_slug=job.voice_slug,
        synthesis_parameters=job.synthesis_parameters,
        queued_at=job.queued_at,
        retry_count=job.retry_count + 1,
    )

    job_id = str(new_job.job_id)
    queue_name = TTS_QUEUE.format(model=new_job.model_slug)

    await redis.hset(TTS_JOBS, job_id, new_job.model_dump_json())
    await redis.zadd(queue_name, {job_id: time.time()})

    logger.info(f"Re-queued job {job_id}, retry_count={new_job.retry_count}")


async def _move_to_dlq(redis: Redis, job: SynthesisJob) -> None:
    dlq_key = TTS_DLQ.format(model=job.model_slug)
    await redis.lpush(dlq_key, job.model_dump_json())
    logger.error(f"Job {job.job_id} moved to DLQ after {MAX_RETRIES} retries")

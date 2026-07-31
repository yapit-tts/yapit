"""Pull-based TTS worker that processes synthesis jobs from Redis queue."""

import asyncio

import redis.asyncio as redis
from loguru import logger

from yapit.contracts import (
    TTS_DLQ,
    TTS_JOB_INDEX,
    TTS_JOBS,
    TTS_PROCESSING,
    TTS_RESULTS,
    SynthesisJob,
    get_queue_name,
)
from yapit.queue import QueueConfig, pull_job, track_processing
from yapit.synth import SynthAdapter, execute_job


async def run_tts_worker(redis_url: str, model: str, adapter: SynthAdapter, worker_id: str) -> None:
    """Process jobs one at a time — a GPU model can only synthesize sequentially."""
    config = QueueConfig(
        queue_name=get_queue_name(model),
        jobs_key=TTS_JOBS,
        processing_pattern=TTS_PROCESSING,
        results_key=TTS_RESULTS,
        job_index_key=TTS_JOB_INDEX,
    )
    processing_key = TTS_PROCESSING.format(worker_id=worker_id)
    dlq_key = TTS_DLQ.format(model=model)

    logger.info(f"TTS worker {worker_id} starting, queue={config.queue_name}")

    await adapter.initialize()
    logger.info(f"TTS worker {worker_id} adapter initialized")

    client = await redis.from_url(redis_url, decode_responses=False)

    try:
        while True:
            pulled = await pull_job(client, config)
            if pulled is None:
                continue

            job = SynthesisJob.model_validate_json(pulled.raw_job)

            await track_processing(
                client, processing_key, pulled.job_id, pulled.raw_job, pulled.retry_count, config.queue_name, dlq_key
            )

            try:
                worker_result = await execute_job(adapter, job, worker_id, pulled.queued_at)
            finally:
                await client.hdel(processing_key, pulled.job_id)

            await client.lpush(TTS_RESULTS, worker_result.model_dump_json())

    except asyncio.CancelledError:
        logger.info(f"TTS worker {worker_id} shutting down")
        raise
    finally:
        await client.aclose()

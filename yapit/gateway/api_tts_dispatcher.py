"""Pulls API-based TTS jobs and dispatches them in parallel."""

import asyncio

import redis.asyncio as redis
from loguru import logger

from yapit.contracts import (
    TTS_JOB_INDEX,
    TTS_JOBS,
    TTS_RESULTS,
    SynthesisJob,
    get_queue_name,
)
from yapit.gateway.backoff import Backoff
from yapit.gateway.metrics import log_error
from yapit.queue import QueueConfig, pull_job
from yapit.synth import SynthAdapter, execute_job


async def run_api_tts_dispatcher(redis_url: str, model: str, adapter: SynthAdapter, worker_id: str) -> None:
    """Spawn a task per job instead of processing sequentially.

    API models handle many concurrent requests, so we don't artificially
    bottleneck. Retry logic is in the adapter.

    No visibility tracking — if the gateway crashes, in-flight jobs are lost
    (acceptable).
    """
    config = QueueConfig(
        queue_name=get_queue_name(model),
        jobs_key=TTS_JOBS,
        results_key=TTS_RESULTS,
        job_index_key=TTS_JOB_INDEX,
    )

    logger.info(f"API dispatcher {worker_id} starting, queue={config.queue_name}")

    await adapter.initialize()
    logger.info(f"API dispatcher {worker_id} adapter initialized")

    client = await redis.from_url(redis_url, decode_responses=False)
    in_flight: set[asyncio.Task] = set()

    async def process_job(raw_job: bytes, queued_at: float) -> None:
        job = SynthesisJob.model_validate_json(raw_job)
        worker_result = await execute_job(adapter, job, worker_id, queued_at)
        await client.lpush(TTS_RESULTS, worker_result.model_dump_json())

    backoff = Backoff()
    try:
        while True:
            try:
                pulled = await pull_job(client, config)
                if pulled is None:
                    continue
                task = asyncio.create_task(process_job(pulled.raw_job, pulled.queued_at))
                in_flight.add(task)
                task.add_done_callback(in_flight.discard)

                backoff.reset()

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.exception(f"API dispatcher error: {e}")
                await log_error(f"API dispatcher {worker_id} loop error: {e}")
                await backoff.sleep()

    except asyncio.CancelledError:
        logger.info(f"API dispatcher {worker_id} shutting down")
        raise
    finally:
        await client.aclose()

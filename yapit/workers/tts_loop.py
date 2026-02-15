"""Pull-based TTS worker that processes synthesis jobs from Redis queue."""

import asyncio
import base64
import time

import redis.asyncio as redis
from loguru import logger

from yapit.contracts import (
    TTS_DLQ,
    TTS_JOB_INDEX,
    TTS_JOBS,
    TTS_PROCESSING,
    TTS_RESULTS,
    SynthesisJob,
    SynthesisResult,
    WorkerResult,
    get_queue_name,
)
from yapit.workers.adapters.base import SynthAdapter
from yapit.workers.queue import QueueConfig, pull_job, track_processing


async def run_tts_worker(redis_url: str, model: str, adapter: SynthAdapter, worker_id: str) -> None:
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
            job_log = logger.bind(
                job_id=str(job.job_id),
                user_id=job.user_id,
                model_slug=job.model_slug,
                voice_slug=job.voice_slug,
                variant_hash=job.variant_hash,
                worker_id=worker_id,
            )
            start_time = time.time()
            queue_wait_ms = int((start_time - pulled.queued_at) * 1000)

            await track_processing(
                client, processing_key, pulled.job_id, pulled.raw_job, pulled.retry_count, config.queue_name, dlq_key
            )

            try:
                synth_result = await _synthesize(adapter, job)
                processing_time_ms = int((time.time() - start_time) * 1000)

                worker_result = WorkerResult(
                    job_id=job.job_id,
                    variant_hash=job.variant_hash,
                    user_id=job.user_id,
                    document_id=job.document_id,
                    block_idx=job.block_idx,
                    model_slug=job.model_slug,
                    voice_slug=job.voice_slug,
                    text_length=len(job.synthesis_parameters.text),
                    usage_multiplier=job.usage_multiplier,
                    worker_id=worker_id,
                    processing_time_ms=processing_time_ms,
                    queue_wait_ms=queue_wait_ms,
                    audio_base64=base64.b64encode(synth_result.audio).decode("ascii"),
                    duration_ms=synth_result.duration_ms,
                )
                job_log.info(
                    f"Job completed: {processing_time_ms}ms processing, "
                    f"{synth_result.duration_ms}ms audio, {len(synth_result.audio)} bytes"
                )

            except Exception as e:
                processing_time_ms = int((time.time() - start_time) * 1000)
                job_log.exception(f"Job failed: {e}")

                worker_result = WorkerResult(
                    job_id=job.job_id,
                    variant_hash=job.variant_hash,
                    user_id=job.user_id,
                    document_id=job.document_id,
                    block_idx=job.block_idx,
                    model_slug=job.model_slug,
                    voice_slug=job.voice_slug,
                    text_length=len(job.synthesis_parameters.text),
                    usage_multiplier=job.usage_multiplier,
                    worker_id=worker_id,
                    processing_time_ms=processing_time_ms,
                    queue_wait_ms=queue_wait_ms,
                    error=str(e),
                )

            finally:
                await client.hdel(processing_key, pulled.job_id)

            await client.lpush(TTS_RESULTS, worker_result.model_dump_json())

    except asyncio.CancelledError:
        logger.info(f"TTS worker {worker_id} shutting down")
    finally:
        await client.aclose()


async def run_api_tts_dispatcher(redis_url: str, model: str, adapter: SynthAdapter, worker_id: str) -> None:
    """Dispatch API-based TTS jobs with unlimited parallelism.

    Unlike run_tts_worker (for GPU models), this spawns a task per job instead of
    processing sequentially. API models like Inworld can handle many concurrent
    requests, so we don't artificially bottleneck. Retry logic is in the adapter.

    No visibility tracking — if gateway crashes, in-flight jobs are lost (acceptable).
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

    async def process_job(job_id: str, raw_job: bytes, queued_at: float) -> None:
        job = SynthesisJob.model_validate_json(raw_job)
        job_log = logger.bind(
            job_id=str(job.job_id),
            user_id=job.user_id,
            model_slug=job.model_slug,
            voice_slug=job.voice_slug,
            variant_hash=job.variant_hash,
            worker_id=worker_id,
        )
        start_time = time.time()
        queue_wait_ms = int((start_time - queued_at) * 1000)

        try:
            synth_result = await _synthesize(adapter, job)
            processing_time_ms = int((time.time() - start_time) * 1000)

            worker_result = WorkerResult(
                job_id=job.job_id,
                variant_hash=job.variant_hash,
                user_id=job.user_id,
                document_id=job.document_id,
                block_idx=job.block_idx,
                model_slug=job.model_slug,
                voice_slug=job.voice_slug,
                text_length=len(job.synthesis_parameters.text),
                usage_multiplier=job.usage_multiplier,
                worker_id=worker_id,
                processing_time_ms=processing_time_ms,
                queue_wait_ms=queue_wait_ms,
                audio_base64=base64.b64encode(synth_result.audio).decode("ascii"),
                duration_ms=synth_result.duration_ms,
            )
            job_log.info(
                f"Job completed: {processing_time_ms}ms processing, "
                f"{synth_result.duration_ms}ms audio, {len(synth_result.audio)} bytes"
            )

        except Exception as e:
            processing_time_ms = int((time.time() - start_time) * 1000)
            job_log.exception(f"Job failed: {e}")

            worker_result = WorkerResult(
                job_id=job.job_id,
                variant_hash=job.variant_hash,
                user_id=job.user_id,
                document_id=job.document_id,
                block_idx=job.block_idx,
                model_slug=job.model_slug,
                voice_slug=job.voice_slug,
                text_length=len(job.synthesis_parameters.text),
                usage_multiplier=job.usage_multiplier,
                worker_id=worker_id,
                processing_time_ms=processing_time_ms,
                queue_wait_ms=queue_wait_ms,
                error=str(e),
            )

        await client.lpush(TTS_RESULTS, worker_result.model_dump_json())

    try:
        while True:
            pulled = await pull_job(client, config)
            if pulled is None:
                continue
            asyncio.create_task(process_job(pulled.job_id, pulled.raw_job, pulled.queued_at))

    except asyncio.CancelledError:
        logger.info(f"API dispatcher {worker_id} shutting down")
    finally:
        await client.aclose()


async def _synthesize(adapter: SynthAdapter, job: SynthesisJob) -> SynthesisResult:
    audio = await adapter.synthesize(
        job.synthesis_parameters.text,
        **job.synthesis_parameters.kwargs,
    )

    if isinstance(audio, str):
        audio = audio.encode()

    return SynthesisResult(
        audio=audio,
        duration_ms=adapter.calculate_duration_ms(audio),
    )

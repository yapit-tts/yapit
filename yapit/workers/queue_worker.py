"""Pull-based worker that processes jobs from Redis queue."""

import asyncio
import base64
import time

import redis.asyncio as redis
from loguru import logger

from yapit.contracts import (
    TTS_JOBS,
    TTS_PROCESSING,
    TTS_RESULTS,
    ProcessingEntry,
    SynthesisJob,
    SynthesisResult,
    WorkerResult,
    get_queue_name,
)
from yapit.workers.adapters.base import SynthAdapter


async def run_worker(redis_url: str, model: str, adapter: SynthAdapter, worker_id: str) -> None:
    queue_name = get_queue_name(model)
    processing_key = TTS_PROCESSING.format(worker_id=worker_id)

    logger.info(f"Worker {worker_id} starting, queue={queue_name}")

    await adapter.initialize()
    logger.info(f"Worker {worker_id} adapter initialized")

    client = await redis.from_url(redis_url, decode_responses=False)

    try:
        while True:
            await _process_one_job(client, queue_name, processing_key, adapter, worker_id)
    except asyncio.CancelledError:
        logger.info(f"Worker {worker_id} shutting down")
    finally:
        await client.aclose()


async def _process_one_job(
    client: redis.Redis,
    queue_name: str,
    processing_key: str,
    adapter: SynthAdapter,
    worker_id: str,
) -> None:
    result = await client.bzpopmin(queue_name, timeout=5)
    if result is None:
        return

    _, job_id_bytes, _ = result
    job_id = job_id_bytes.decode()

    job_json = await client.hget(TTS_JOBS, job_id)
    if job_json is None:
        logger.info(f"Job {job_id} evicted before processing")
        return

    await client.hdel(TTS_JOBS, job_id)

    job = SynthesisJob.model_validate_json(job_json)
    start_time = time.time()

    entry = ProcessingEntry(processing_started=start_time, job=job)
    await client.hset(processing_key, job_id, entry.model_dump_json())

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
            worker_id=worker_id,
            processing_time_ms=processing_time_ms,
            audio_base64=base64.b64encode(synth_result.audio).decode("ascii"),
            duration_ms=synth_result.duration_ms,
            audio_tokens=synth_result.audio_tokens,
        )
        logger.info(
            f"Job {job.job_id} completed: {processing_time_ms}ms processing, "
            f"{synth_result.duration_ms}ms audio, {len(synth_result.audio)} bytes"
        )

    except Exception as e:
        processing_time_ms = int((time.time() - start_time) * 1000)
        logger.exception(f"Job {job.job_id} failed: {e}")

        worker_result = WorkerResult(
            job_id=job.job_id,
            variant_hash=job.variant_hash,
            user_id=job.user_id,
            document_id=job.document_id,
            block_idx=job.block_idx,
            model_slug=job.model_slug,
            voice_slug=job.voice_slug,
            text_length=len(job.synthesis_parameters.text),
            worker_id=worker_id,
            processing_time_ms=processing_time_ms,
            error=str(e),
        )

    finally:
        await client.hdel(processing_key, job_id)

    await client.lpush(TTS_RESULTS, worker_result.model_dump_json())


async def _synthesize(adapter: SynthAdapter, job: SynthesisJob) -> SynthesisResult:
    audio = await adapter.synthesize(
        job.synthesis_parameters.text,
        **job.synthesis_parameters.kwargs,
    )

    if isinstance(audio, str):
        audio = audio.encode()

    audio_tokens = None
    if hasattr(adapter, "get_audio_tokens"):
        audio_tokens = adapter.get_audio_tokens()

    return SynthesisResult(
        audio=audio,
        duration_ms=adapter.calculate_duration_ms(audio),
        audio_tokens=audio_tokens,
    )

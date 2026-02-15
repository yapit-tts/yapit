"""Scans for stale jobs and sends them to RunPod overflow.

Uses AsyncioEndpoint for native async — submits all stale jobs at once,
polls outstanding handles across scan cycles. No threads blocked.
"""

import asyncio
import json
import time
import uuid
from dataclasses import dataclass

import aiohttp
from loguru import logger
from redis.asyncio import Redis
from runpod import AsyncioEndpoint, AsyncioJob

from yapit.contracts import (
    TTS_RESULTS,
    YOLO_RESULT,
    YoloResult,
    build_tts_dlq_error,
    parse_queue_name,
)
from yapit.gateway.config import Settings
from yapit.gateway.metrics import log_error, log_event
from yapit.workers.queue import move_to_dlq, requeue_job


@dataclass
class ScannerContext:
    queue_name: str
    jobs_key: str
    dlq_key: str
    max_retries: int
    result_key_pattern: str
    queue_type: str
    model_slug: str | None
    worker_id: str
    name: str


@dataclass
class _OutstandingJob:
    handle: AsyncioJob
    job_id: str
    raw_job: str
    retry_count: int
    queue_wait_ms: int
    submitted_at: float


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
    max_retries: int,
    dlq_key: str,
) -> None:
    if not settings.runpod_api_key or not settings.runpod_request_timeout_seconds:
        logger.warning(f"{name} scanner disabled: missing RunPod API key or timeout config")
        return

    import runpod

    runpod.api_key = settings.runpod_api_key
    runpod_timeout = settings.runpod_request_timeout_seconds

    session = aiohttp.ClientSession()
    endpoint = AsyncioEndpoint(endpoint_id, session)
    outstanding: list[_OutstandingJob] = []

    queue_type, model_slug = parse_queue_name(queue_name)

    ctx = ScannerContext(
        queue_name=queue_name,
        jobs_key=jobs_key,
        dlq_key=dlq_key,
        max_retries=max_retries,
        result_key_pattern=result_key_pattern,
        queue_type=queue_type,
        model_slug=model_slug,
        worker_id=f"{name}-runpod",
        name=name,
    )

    scanner_log = logger.bind(queue_type=queue_type, model_slug=model_slug, worker_id=ctx.worker_id)
    scanner_log.info(f"{name} scanner starting (queue={queue_name}, threshold={overflow_threshold_s}s)")

    try:
        while True:
            try:
                await _claim_and_submit(redis, endpoint, outstanding, ctx, job_index_key, overflow_threshold_s)
                await _poll_outstanding(redis, outstanding, ctx, runpod_timeout)
                await asyncio.sleep(scan_interval_s)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                scanner_log.exception(f"Error in {name} scanner: {e}")
                await log_error(f"Overflow scanner {name} loop error: {e}")
                await asyncio.sleep(scan_interval_s)
    finally:
        await session.close()


async def _claim_and_submit(
    redis: Redis,
    endpoint: AsyncioEndpoint,
    outstanding: list[_OutstandingJob],
    ctx: ScannerContext,
    job_index_key: str | None,
    overflow_threshold_s: int,
) -> None:
    cutoff = time.time() - overflow_threshold_s
    stale_entries = await redis.zrangebyscore(ctx.queue_name, "-inf", cutoff, withscores=True)
    if not stale_entries:
        return

    for job_id_bytes, queued_score in stale_entries:
        job_id = job_id_bytes.decode() if isinstance(job_id_bytes, bytes) else job_id_bytes

        removed = await redis.zrem(ctx.queue_name, job_id)
        if not removed:
            continue

        wrapper_json = await redis.hget(ctx.jobs_key, job_id)
        if wrapper_json is None:
            continue

        await redis.hdel(ctx.jobs_key, job_id)
        wrapper = json.loads(wrapper_json)
        raw_job = wrapper["job"]
        retry_count = wrapper.get("retry_count", 0)

        if job_index_key and "index_key" in wrapper:
            await redis.hdel(job_index_key, wrapper["index_key"])

        age = time.time() - queued_score
        queue_wait_ms = int(age * 1000)

        logger.bind(queue_type=ctx.queue_type, model_slug=ctx.model_slug, job_id=job_id).info(
            f"{ctx.name}: job stale for {age:.1f}s, sending to RunPod"
        )
        await log_event(
            "job_overflow",
            queue_type=ctx.queue_type,
            model_slug=ctx.model_slug,
            queue_wait_ms=queue_wait_ms,
            data={"job_id": job_id},
        )

        try:
            job_data = json.loads(raw_job)
            handle = await endpoint.run(job_data)
            outstanding.append(
                _OutstandingJob(
                    handle=handle,
                    job_id=job_id,
                    raw_job=raw_job,
                    retry_count=retry_count,
                    queue_wait_ms=queue_wait_ms,
                    submitted_at=time.time(),
                )
            )
        except Exception as e:
            logger.bind(queue_type=ctx.queue_type, model_slug=ctx.model_slug, job_id=job_id).exception(
                f"{ctx.name}: failed to submit to RunPod: {e}"
            )
            await _handle_failure(
                redis, job_id, raw_job, retry_count, queue_wait_ms, 0, f"RunPod submission failed: {e}", ctx
            )


async def _poll_outstanding(
    redis: Redis,
    outstanding: list[_OutstandingJob],
    ctx: ScannerContext,
    runpod_timeout: int,
) -> None:
    still_outstanding: list[_OutstandingJob] = []

    for oj in outstanding:
        try:
            status = await oj.handle.status()
        except Exception as e:
            logger.bind(queue_type=ctx.queue_type, model_slug=ctx.model_slug, job_id=oj.job_id).exception(
                f"{ctx.name}: status check failed: {e}"
            )
            processing_time_ms = int((time.time() - oj.submitted_at) * 1000)
            await _handle_failure(
                redis,
                oj.job_id,
                oj.raw_job,
                oj.retry_count,
                oj.queue_wait_ms,
                processing_time_ms,
                f"Status check failed: {e}",
                ctx,
            )
            continue

        if status == "COMPLETED":
            try:
                output = await oj.handle.output()
            except Exception as e:
                logger.bind(queue_type=ctx.queue_type, model_slug=ctx.model_slug, job_id=oj.job_id).exception(
                    f"{ctx.name}: output fetch failed: {e}"
                )
                processing_time_ms = int((time.time() - oj.submitted_at) * 1000)
                await _handle_failure(
                    redis,
                    oj.job_id,
                    oj.raw_job,
                    oj.retry_count,
                    oj.queue_wait_ms,
                    processing_time_ms,
                    f"Output fetch failed: {e}",
                    ctx,
                )
                continue

            if isinstance(output, dict) and "error" in output:
                processing_time_ms = int((time.time() - oj.submitted_at) * 1000)
                await _handle_failure(
                    redis,
                    oj.job_id,
                    oj.raw_job,
                    oj.retry_count,
                    oj.queue_wait_ms,
                    processing_time_ms,
                    f"RunPod handler error: {output['error']}",
                    ctx,
                )
                continue

            await _handle_completed(redis, oj, output, ctx)

        elif status in ("FAILED", "ERROR", "CANCELLED"):
            processing_time_ms = int((time.time() - oj.submitted_at) * 1000)
            await _handle_failure(
                redis,
                oj.job_id,
                oj.raw_job,
                oj.retry_count,
                oj.queue_wait_ms,
                processing_time_ms,
                f"RunPod job {status}",
                ctx,
            )

        elif time.time() - oj.submitted_at > runpod_timeout:
            processing_time_ms = int((time.time() - oj.submitted_at) * 1000)
            await _handle_failure(
                redis,
                oj.job_id,
                oj.raw_job,
                oj.retry_count,
                oj.queue_wait_ms,
                processing_time_ms,
                f"Timed out after {runpod_timeout}s",
                ctx,
            )

        else:
            still_outstanding.append(oj)

    outstanding.clear()
    outstanding.extend(still_outstanding)


async def _handle_completed(
    redis: Redis,
    oj: _OutstandingJob,
    output: dict,
    ctx: ScannerContext,
) -> None:
    processing_time_ms = int((time.time() - oj.submitted_at) * 1000)
    logger.bind(queue_type=ctx.queue_type, model_slug=ctx.model_slug, job_id=oj.job_id).info(
        f"{ctx.name}: job completed in {processing_time_ms}ms"
    )

    await log_event(
        "overflow_complete",
        queue_type=ctx.queue_type,
        model_slug=ctx.model_slug,
        worker_latency_ms=processing_time_ms,
        worker_id=ctx.worker_id,
        data={"job_id": oj.job_id},
    )

    output["job_id"] = oj.job_id
    output["worker_id"] = ctx.worker_id
    output["processing_time_ms"] = processing_time_ms
    output["queue_wait_ms"] = oj.queue_wait_ms

    result_key = ctx.result_key_pattern.format(job_id=oj.job_id)
    await redis.lpush(result_key, json.dumps(output))


async def _handle_failure(
    redis: Redis,
    job_id: str,
    raw_job: str,
    retry_count: int,
    queue_wait_ms: int,
    processing_time_ms: int,
    error: str,
    ctx: ScannerContext,
) -> None:
    logger.bind(queue_type=ctx.queue_type, model_slug=ctx.model_slug, job_id=job_id).warning(
        f"{ctx.name}: job failed (retry {retry_count}/{ctx.max_retries}): {error}"
    )

    await log_event(
        "overflow_error",
        queue_type=ctx.queue_type,
        model_slug=ctx.model_slug,
        worker_latency_ms=processing_time_ms,
        worker_id=ctx.worker_id,
        data={"job_id": job_id, "error": error},
    )

    if retry_count < ctx.max_retries:
        await requeue_job(redis, ctx.queue_name, ctx.jobs_key, job_id, raw_job.encode(), retry_count)
        await log_event(
            "job_requeued",
            queue_type=ctx.queue_type,
            model_slug=ctx.model_slug,
            retry_count=retry_count + 1,
            data={"job_id": job_id, "source": "overflow"},
        )
        return

    await move_to_dlq(redis, ctx.dlq_key, job_id, raw_job.encode(), retry_count)
    await log_event(
        "job_dlq",
        queue_type=ctx.queue_type,
        model_slug=ctx.model_slug,
        retry_count=retry_count,
        data={"job_id": job_id, "source": "overflow"},
    )

    if ctx.queue_type == "tts":
        error_result = build_tts_dlq_error(raw_job, error, worker_id=ctx.worker_id)
        await redis.lpush(TTS_RESULTS, error_result.model_dump_json())
    elif ctx.queue_type == "yolo":
        yolo_error = YoloResult(
            job_id=uuid.UUID(job_id),
            figures=[],
            page_width=None,
            page_height=None,
            worker_id=ctx.worker_id,
            processing_time_ms=processing_time_ms,
            error=error,
        )
        result_key = YOLO_RESULT.format(job_id=job_id)
        await redis.lpush(result_key, yolo_error.model_dump_json())
        await redis.expire(result_key, 300)

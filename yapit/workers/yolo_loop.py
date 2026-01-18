"""Pull-based YOLO worker that processes detection jobs from Redis queue."""

import asyncio
import base64
import time

import redis.asyncio as redis
from loguru import logger

from yapit.contracts import (
    YOLO_DLQ,
    YOLO_JOBS,
    YOLO_PROCESSING,
    YOLO_QUEUE,
    YOLO_RESULT,
    DetectedFigure,
    YoloJob,
    YoloResult,
)
from yapit.workers.queue import QueueConfig, pull_job, track_processing

_CONFIG = QueueConfig(queue_name=YOLO_QUEUE, jobs_key=YOLO_JOBS, processing_pattern=YOLO_PROCESSING)


async def run_yolo_worker(redis_url: str, worker_id: str, detect_fn) -> None:
    """Run YOLO detection worker.

    Args:
        redis_url: Redis connection URL
        worker_id: Unique worker identifier
        detect_fn: Detection function (page_image: bytes, width: int, height: int) -> list[DetectedFigure]
    """
    processing_key = YOLO_PROCESSING.format(worker_id=worker_id)
    logger.info(f"YOLO worker {worker_id} starting, queue={_CONFIG.queue_name}")

    client = await redis.from_url(redis_url, decode_responses=False)

    try:
        while True:
            pulled = await pull_job(client, _CONFIG)
            if pulled is None:
                continue

            job = YoloJob.model_validate_json(pulled.raw_job)
            start_time = time.time()

            await track_processing(
                client, processing_key, pulled.job_id, pulled.raw_job, pulled.retry_count, _CONFIG.queue_name, YOLO_DLQ
            )

            try:
                image_bytes = base64.b64decode(job.image_base64)
                figures = detect_fn(image_bytes, job.page_width, job.page_height)
                processing_time_ms = int((time.time() - start_time) * 1000)

                result = YoloResult(
                    job_id=job.job_id,
                    figures=[
                        DetectedFigure(
                            bbox=f.bbox,
                            confidence=f.confidence,
                            width_pct=f.width_pct,
                            row_group=f.row_group,
                        )
                        for f in figures
                    ],
                    worker_id=worker_id,
                    processing_time_ms=processing_time_ms,
                )
                logger.info(f"YOLO job {job.job_id} completed: {processing_time_ms}ms, {len(figures)} figures")

            except Exception as e:
                processing_time_ms = int((time.time() - start_time) * 1000)
                logger.exception(f"YOLO job {job.job_id} failed: {e}")

                result = YoloResult(
                    job_id=job.job_id,
                    figures=[],
                    worker_id=worker_id,
                    processing_time_ms=processing_time_ms,
                    error=str(e),
                )

            finally:
                await client.hdel(processing_key, pulled.job_id)

            # Push result to per-job list for BRPOP by caller
            result_key = YOLO_RESULT.format(job_id=str(job.job_id))
            await client.lpush(result_key, result.model_dump_json())
            await client.expire(result_key, 300)

    except asyncio.CancelledError:
        logger.info(f"YOLO worker {worker_id} shutting down")
    finally:
        await client.aclose()

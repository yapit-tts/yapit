"""YOLO figure detection client - enqueues jobs and waits for results."""

import base64
import uuid

from redis.asyncio import Redis

from yapit.contracts import (
    YOLO_JOBS,
    YOLO_QUEUE,
    YOLO_RESULT,
    YoloJob,
    YoloResult,
)
from yapit.workers.queue import QueueConfig, push_job

YOLO_RESULT_TIMEOUT_S = 60

_yolo_config = QueueConfig(
    queue_name=YOLO_QUEUE,
    jobs_key=YOLO_JOBS,
    processing_pattern="",  # not used for enqueue
)


async def enqueue_detection(
    redis: Redis,
    page_image: bytes,
    page_width: int,
    page_height: int,
) -> str:
    """Put a YOLO detection job on the queue. Returns job_id."""
    job_id = uuid.uuid4()
    job = YoloJob(
        job_id=job_id,
        image_base64=base64.b64encode(page_image).decode(),
        page_width=page_width,
        page_height=page_height,
    )
    await push_job(redis, _yolo_config, str(job_id), job.model_dump_json().encode())
    return str(job_id)


async def wait_for_result(redis: Redis, job_id: str, timeout: float = YOLO_RESULT_TIMEOUT_S) -> YoloResult:
    """Wait for a YOLO detection result using BRPOP."""
    result_key = YOLO_RESULT.format(job_id=job_id)

    result = await redis.brpop([result_key], timeout=int(timeout))
    if result is None:
        return YoloResult(
            job_id=uuid.UUID(job_id),
            figures=[],
            worker_id="timeout",
            processing_time_ms=0,
            error="Timeout waiting for YOLO result",
        )

    _, result_json = result
    return YoloResult.model_validate_json(result_json)

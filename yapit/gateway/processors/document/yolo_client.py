"""YOLO figure detection client - handles queue distribution and worker communication."""

import asyncio
import base64
import os
import uuid

import httpx
from loguru import logger
from pydantic import BaseModel
from redis.asyncio import Redis

from yapit.gateway.config import Settings

YOLO_QUEUE = "yolo:queue"
YOLO_RESULT_PREFIX = "yolo:result:"
YOLO_RESULT_TTL = 300

WORKER_URL = os.getenv("YOLO_WORKER_URL", "http://yolo-cpu:8000")


class DetectedFigure(BaseModel):
    bbox: tuple[float, float, float, float]
    confidence: float
    width_pct: float
    row_group: str | None


class YoloJob(BaseModel):
    job_id: str
    image_base64: str
    page_width: int
    page_height: int


class YoloResult(BaseModel):
    job_id: str
    figures: list[DetectedFigure]
    error: str | None = None


async def enqueue_detection(
    redis: Redis,
    page_image: bytes,
    page_width: int,
    page_height: int,
) -> str:
    """Put a YOLO detection job on the queue. Returns job_id."""
    job_id = str(uuid.uuid4())
    job = YoloJob(
        job_id=job_id,
        image_base64=base64.b64encode(page_image).decode(),
        page_width=page_width,
        page_height=page_height,
    )
    await redis.lpush(YOLO_QUEUE, job.model_dump_json())
    return job_id


async def wait_for_result(redis: Redis, job_id: str, timeout: float = 60.0) -> YoloResult:
    """Wait for a YOLO detection result."""
    result_key = f"{YOLO_RESULT_PREFIX}{job_id}"
    start = asyncio.get_event_loop().time()

    while True:
        result_data = await redis.get(result_key)
        if result_data:
            await redis.delete(result_key)
            return YoloResult.model_validate_json(result_data)

        if asyncio.get_event_loop().time() - start > timeout:
            return YoloResult(job_id=job_id, figures=[], error="Timeout waiting for YOLO result")

        await asyncio.sleep(0.05)


class YoloProcessor:
    """Background processor that pulls YOLO jobs from queue and calls workers."""

    def __init__(self, redis: Redis, settings: Settings):
        self._redis = redis
        self._settings = settings
        self._client: httpx.AsyncClient | None = None

    async def initialize(self) -> None:
        self._client = httpx.AsyncClient(timeout=60.0)
        logger.info(f"YOLO processor initialized, worker URL: {WORKER_URL}")

    def _should_use_overflow(self) -> bool:
        """Check if we should route to overflow (RunPod CPU).

        TODO: Implement overflow routing based on queue depth or residency time.
        For now, always returns False (use local workers only).
        """
        return False

    async def run(self) -> None:
        """Main processing loop - pull jobs from Redis queue."""
        await self.initialize()

        # Match worker replica count so all workers can be utilized
        semaphore = asyncio.Semaphore(self._settings.yolo_cpu_replicas)

        async def process_and_release(raw: bytes) -> None:
            try:
                await self._handle_job(raw)
            finally:
                semaphore.release()

        while True:
            try:
                await semaphore.acquire()
                result = await self._redis.brpop([YOLO_QUEUE], timeout=1)
                if result is None:
                    semaphore.release()
                    continue
                _, raw = result
                asyncio.create_task(process_and_release(raw))
            except Exception as e:
                semaphore.release()
                logger.error(f"Error in YOLO processor loop: {e}")
                await asyncio.sleep(1)

    async def _handle_job(self, raw: bytes) -> None:
        """Process a single YOLO job."""
        job = YoloJob.model_validate_json(raw)
        result_key = f"{YOLO_RESULT_PREFIX}{job.job_id}"

        try:
            # TODO: Check _should_use_overflow() and route to RunPod if needed
            response = await self._client.post(
                f"{WORKER_URL}/detect",
                json={
                    "image_base64": job.image_base64,
                    "page_width": job.page_width,
                    "page_height": job.page_height,
                },
            )
            response.raise_for_status()
            data = response.json()

            result = YoloResult(
                job_id=job.job_id,
                figures=[DetectedFigure(**f) for f in data["figures"]],
            )
        except Exception as e:
            logger.error(f"YOLO detection failed for job {job.job_id}: {e}")
            result = YoloResult(job_id=job.job_id, figures=[], error=str(e))

        await self._redis.setex(result_key, YOLO_RESULT_TTL, result.model_dump_json())

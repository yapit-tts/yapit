"""The TTS queue's order across retries, against a real Redis."""

import time

from yapit.contracts import TTS_JOBS, TTS_PROCESSING, get_queue_name
from yapit.gateway.visibility_scanner import _scan_processing_sets
from yapit.queue import QueueConfig, pull_job, push_job, track_processing

QUEUE = get_queue_name("kokoro")
CONFIG = QueueConfig(queue_name=QUEUE, jobs_key=TTS_JOBS)


async def test_a_retried_job_keeps_its_late_score(app):
    redis = app.state.redis_client
    late = time.time() + 120
    await push_job(redis, CONFIG, "job-block", b"{}", score=late)

    pulled = await pull_job(redis, CONFIG, timeout=1)
    assert pulled is not None
    processing_key = TTS_PROCESSING.format(worker_id="stuck-worker")
    await track_processing(
        redis, processing_key, pulled.job_id, pulled.raw_job, pulled.retry_count, pulled.score, QUEUE, "dlq"
    )

    await _scan_processing_sets(redis, "tts:processing:*", TTS_JOBS, visibility_timeout_s=0, max_retries=3)

    assert await redis.zscore(QUEUE, "job-block") == late

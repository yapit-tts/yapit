"""The TTS queue's order and the result consumer's finalization, against a real Redis."""

import base64
import time
import uuid

from yapit.contracts import (
    TTS_AUDIO_CACHE,
    TTS_BILLING_STREAM,
    TTS_INFLIGHT,
    TTS_JOBS,
    TTS_PROCESSING,
    WorkerResult,
    get_queue_name,
)
from yapit.gateway.result_consumer import _process_result
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


def worker_result(job_id: uuid.UUID, variant_hash: str) -> WorkerResult:
    return WorkerResult(
        job_id=job_id,
        variant_hash=variant_hash,
        user_id="listener",
        document_id=uuid.uuid4(),
        block_idx=0,
        model_slug="kokoro",
        voice_slug="af_heart",
        text_length=12,
        usage_multiplier=1.0,
        worker_id="stub",
        processing_time_ms=1,
        queue_wait_ms=1,
        audio_base64=base64.b64encode(b"OggS audio").decode(),
        duration_ms=1000,
    )


async def test_a_result_whose_marker_expired_is_kept_and_billed(app):
    redis = app.state.redis_client

    await _process_result(redis, worker_result(uuid.uuid4(), "late"))

    assert await redis.get(TTS_AUDIO_CACHE.format(hash="late")) == b"OggS audio"
    assert await redis.xlen(TTS_BILLING_STREAM) == 1


async def test_a_result_leaves_the_marker_of_another_job_for_its_variant(app):
    redis = app.state.redis_client
    expired_job, current_job = uuid.uuid4(), uuid.uuid4()
    await redis.set(TTS_INFLIGHT.format(hash="shared"), str(current_job))

    await _process_result(redis, worker_result(expired_job, "shared"))
    assert await redis.get(TTS_INFLIGHT.format(hash="shared")) == str(current_job).encode()

    await _process_result(redis, worker_result(current_job, "shared"))
    assert await redis.get(TTS_INFLIGHT.format(hash="shared")) is None
    assert await redis.xlen(TTS_BILLING_STREAM) == 1


async def test_a_duplicate_result_is_billed_once(app):
    redis = app.state.redis_client
    job_id = uuid.uuid4()
    await redis.set(TTS_INFLIGHT.format(hash="retried"), str(job_id))

    await _process_result(redis, worker_result(job_id, "retried"))
    await _process_result(redis, worker_result(job_id, "retried"))

    assert await redis.xlen(TTS_BILLING_STREAM) == 1

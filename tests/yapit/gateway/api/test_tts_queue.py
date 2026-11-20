"""The TTS queue's order and the result consumer's finalization, against a real Redis."""

import asyncio
import base64
import time
import uuid

from yapit.contracts import (
    TTS_AUDIO_CACHE,
    TTS_BILLING_STREAM,
    TTS_INFLIGHT,
    TTS_JOBS,
    SynthesisJob,
    SynthesisParameters,
    WorkerResult,
    get_queue_name,
)
from yapit.gateway.result_consumer import _process_result
from yapit.gateway.visibility_scanner import _scan_processing_sets
from yapit.queue import QueueConfig, push_job
from yapit.synth import SynthAdapter
from yapit.workers.tts_loop import run_tts_worker

QUEUE = get_queue_name("kokoro")
CONFIG = QueueConfig(queue_name=QUEUE, jobs_key=TTS_JOBS)


class StuckAdapter(SynthAdapter):
    """A worker's model that takes a job and never finishes it."""

    def __init__(self):
        self.took_a_job = asyncio.Event()

    async def initialize(self) -> None:
        pass

    async def synthesize(self, text: str, **kwargs) -> bytes:
        self.took_a_job.set()
        await asyncio.Future()
        raise AssertionError("unreachable")

    def calculate_duration_ms(self, audio_bytes: bytes) -> int:
        raise AssertionError("never synthesizes")


async def test_a_retried_job_keeps_its_late_score(app, _test_settings):
    redis = app.state.redis_client
    late = time.time() + 120
    job = SynthesisJob(
        job_id=uuid.uuid4(),
        variant_hash="job-block",
        user_id="reader",
        document_id=uuid.uuid4(),
        block_idx=0,
        model_slug="kokoro",
        voice_slug="af_heart",
        usage_multiplier=1.0,
        synthesis_parameters=SynthesisParameters(model="kokoro", voice="af_heart", text="A block."),
    )
    await push_job(redis, CONFIG, str(job.job_id), job.model_dump_json().encode(), score=late)

    adapter = StuckAdapter()
    worker = asyncio.create_task(run_tts_worker(_test_settings.redis_url, "kokoro", adapter, "stuck-worker"))
    try:
        await asyncio.wait_for(adapter.took_a_job.wait(), timeout=10)
        await _scan_processing_sets(redis, "tts:processing:*", TTS_JOBS, visibility_timeout_s=0, max_retries=3)
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)

    assert await redis.zscore(QUEUE, str(job.job_id)) == late


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


async def test_an_error_result_leaves_the_marker_of_another_job_for_its_variant(app):
    redis = app.state.redis_client
    failed_job, current_job = uuid.uuid4(), uuid.uuid4()
    await redis.set(TTS_INFLIGHT.format(hash="shared"), str(current_job))
    failed = worker_result(failed_job, "shared").model_copy(update={"audio_base64": None, "error": "Synthesis failed"})

    await _process_result(redis, failed)

    assert await redis.get(TTS_INFLIGHT.format(hash="shared")) == str(current_job).encode()

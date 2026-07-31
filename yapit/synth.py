"""How a TTS model is called, and how one job is run."""

import base64
import json
import time
from abc import ABC, abstractmethod
from typing import TypedDict, Unpack

from loguru import logger

from yapit.contracts import SynthesisJob, SynthesisResult, WorkerResult


# ty doesn't accept a TypedDict bound on a type parameter yet; the runtime contract is fine.
class SynthAdapter[SynthesisParameters: TypedDict](ABC):  # ty: ignore[invalid-type-form]
    @abstractmethod
    async def initialize(self) -> None: ...

    @abstractmethod
    async def synthesize(self, text: str, **kwargs: Unpack[SynthesisParameters]) -> bytes | str:  # ty: ignore[invalid-type-form]
        """Synthesize text to pcm audio bytes."""

    @abstractmethod
    def calculate_duration_ms(self, audio_bytes: bytes) -> int:
        """Calculate audio duration in milliseconds from pcm audio bytes."""

    def get_word_timestamps(self) -> list[dict] | None:
        """Word-level timestamps from last synthesis, or None if unsupported."""
        return None


async def execute_job(adapter: SynthAdapter, job: SynthesisJob, worker_id: str, queued_at: float) -> WorkerResult:
    """Synthesize one job. Failures come back as an error result, not an exception."""
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

    def build_result(
        *,
        audio_base64: str | None = None,
        duration_ms: int | None = None,
        word_timestamps_json: str | None = None,
        error: str | None = None,
        error_detail: str | None = None,
    ) -> WorkerResult:
        return WorkerResult(
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
            processing_time_ms=int((time.time() - start_time) * 1000),
            queue_wait_ms=queue_wait_ms,
            audio_base64=audio_base64,
            duration_ms=duration_ms,
            word_timestamps_json=word_timestamps_json,
            error=error,
            error_detail=error_detail,
        )

    try:
        synth_result = await _synthesize(adapter, job)
    except Exception as e:
        job_log.exception(f"Job failed: {e}")
        return build_result(error="Synthesis failed", error_detail=str(e))

    worker_result = build_result(
        audio_base64=base64.b64encode(synth_result.audio).decode("ascii"),
        duration_ms=synth_result.duration_ms,
        word_timestamps_json=synth_result.word_timestamps_json,
    )
    job_log.info(
        f"Job completed: {worker_result.processing_time_ms}ms processing, "
        f"{synth_result.duration_ms}ms audio, {len(synth_result.audio)} bytes"
    )
    return worker_result


async def _synthesize(adapter: SynthAdapter, job: SynthesisJob) -> SynthesisResult:
    audio = await adapter.synthesize(
        job.synthesis_parameters.text,
        **job.synthesis_parameters.kwargs,
    )

    if isinstance(audio, str):
        audio = audio.encode()

    word_ts = adapter.get_word_timestamps()
    return SynthesisResult(
        audio=audio,
        duration_ms=adapter.calculate_duration_ms(audio),
        word_timestamps_json=json.dumps(word_ts) if word_ts else None,
    )

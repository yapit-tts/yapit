"""Contracts for Redis keys, queues, and job processing."""

import uuid
from typing import Annotated, Final

import annotated_types
from pydantic import BaseModel, ConfigDict, Field

TTS_INFLIGHT: Final[str] = "tts:inflight:{hash}"
TTS_SUBSCRIBERS: Final[str] = "tts:subscribers:{hash}"
TTS_CURSOR: Final[str] = "tts:cursor:{user_id}:{document_id}"
TTS_PENDING: Final[str] = "tts:pending:{user_id}:{document_id}"

# Queue structure (sorted set + hashes for efficient eviction)
TTS_QUEUE: Final[str] = "tts:queue:{model}"  # sorted set: job_id -> timestamp
TTS_JOBS: Final[str] = "tts:jobs"  # hash: job_id -> job_json
TTS_JOB_INDEX: Final[str] = "tts:job_index"  # hash: "user_id:doc_id:block_idx" -> job_id

TTS_RESULTS: Final[str] = "tts:results"
TTS_PROCESSING: Final[str] = "tts:processing:{worker_id}"
TTS_DLQ: Final[str] = "tts:dlq:{model}"

YOLO_QUEUE: Final[str] = "yolo:queue"  # sorted set: job_id -> timestamp
YOLO_JOBS: Final[str] = "yolo:jobs"  # hash: job_id -> job_json
YOLO_PROCESSING: Final[str] = "yolo:processing:{worker_id}"
YOLO_DLQ: Final[str] = "yolo:dlq"
YOLO_RESULT: Final[str] = "yolo:result:{job_id}"  # list for BRPOP result delivery


def get_queue_name(model: str) -> str:
    return TTS_QUEUE.format(model=model)


def get_pubsub_channel(user_id: str) -> str:
    return f"tts:done:{user_id}"


class SynthesisParameters(BaseModel):
    """Parameters for TTS synthesis."""

    model: str
    voice: str
    text: str
    codec: str  # codec the worker must produce / translate to
    kwargs: dict = Field(default_factory=dict)  # additional parameters for the worker
    # For HIGGS context accumulation: base64-encoded serialized audio token tensors from previous blocks
    context_tokens: str | None = None

    model_config = ConfigDict(frozen=True)


class SynthesisJob(BaseModel):
    """Job pushed to queue, processed by workers."""

    job_id: uuid.UUID
    variant_hash: str
    user_id: str
    document_id: uuid.UUID
    block_idx: int
    model_slug: str
    voice_slug: str
    usage_multiplier: float  # From TTSModel, for billing without DB query on finalize

    synthesis_parameters: SynthesisParameters

    model_config = ConfigDict(frozen=True)


class SynthesisResult(BaseModel):
    audio: Annotated[bytes, annotated_types.MaxLen(10 * 1024 * 1024)]
    duration_ms: int
    audio_tokens: str | None = None


class WorkerResult(BaseModel):
    """Pushed to tts:results by workers. Contains everything for finalization."""

    job_id: uuid.UUID
    variant_hash: str
    user_id: str
    document_id: uuid.UUID
    block_idx: int
    model_slug: str
    voice_slug: str
    text_length: int
    usage_multiplier: float

    worker_id: str
    processing_time_ms: int

    audio_base64: str | None = None
    duration_ms: int | None = None
    audio_tokens: str | None = None
    error: str | None = None


class YoloJob(BaseModel):
    """YOLO detection job pushed to queue."""

    job_id: uuid.UUID
    image_base64: str
    page_width: int
    page_height: int

    model_config = ConfigDict(frozen=True)


class DetectedFigure(BaseModel):
    """A figure detected by YOLO."""

    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 normalized 0-1
    confidence: float
    width_pct: float
    row_group: str | None = None


class YoloResult(BaseModel):
    """YOLO detection result."""

    job_id: uuid.UUID
    figures: list[DetectedFigure]
    worker_id: str
    processing_time_ms: int
    error: str | None = None

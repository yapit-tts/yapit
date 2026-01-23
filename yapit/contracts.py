"""Contracts for Redis keys, queues, and job processing."""

import uuid
from typing import Annotated, Final

import annotated_types
from pydantic import BaseModel, ConfigDict, Field

TTS_INFLIGHT: Final[str] = "tts:inflight:{hash}"
TTS_SUBSCRIBERS: Final[str] = "tts:subscribers:{hash}"
TTS_CURSOR: Final[str] = "tts:cursor:{user_id}:{document_id}"
TTS_PENDING: Final[str] = "tts:pending:{user_id}:{document_id}"

# Rate limiting
RATELIMIT_EXTRACTION: Final[str] = "ratelimit:extraction:{user_id}"
MAX_CONCURRENT_EXTRACTIONS: Final[int] = 3
RATELIMIT_TTS: Final[str] = "ratelimit:tts:{user_id}"
MAX_TTS_REQUESTS_PER_MINUTE: Final[int] = 300

# Document storage limits
MAX_DOCUMENTS_GUEST: Final[int] = 50
MAX_DOCUMENTS_FREE: Final[int] = 100
MAX_DOCUMENTS_PAID: Final[int] = 1000

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


def parse_queue_name(queue_name: str) -> tuple[str, str | None]:
    """Parse queue_name like 'tts:queue:kokoro' into (queue_type, model_slug)."""
    parts = queue_name.split(":")
    queue_type = parts[0]
    model_slug = parts[2] if len(parts) > 2 else None
    return queue_type, model_slug


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
    queue_wait_ms: int

    audio_base64: str | None = None
    duration_ms: int | None = None
    audio_tokens: str | None = None
    error: str | None = None


class YoloJob(BaseModel):
    """YOLO detection job pushed to queue.

    Worker receives single-page PDF bytes, renders the page, runs detection,
    crops detected figures, and returns everything in YoloResult.
    """

    job_id: uuid.UUID
    page_pdf_base64: str  # single-page PDF bytes

    model_config = ConfigDict(frozen=True)


class DetectedFigure(BaseModel):
    """A figure detected by YOLO, with cropped image data."""

    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 normalized 0-1
    confidence: float
    width_pct: float
    row_group: str | None = None
    cropped_image_base64: str  # cropped PNG bytes


class YoloResult(BaseModel):
    """YOLO detection result including rendered page dimensions and cropped figures."""

    job_id: uuid.UUID
    figures: list[DetectedFigure]
    page_width: int | None  # rendered dimensions, None on error
    page_height: int | None
    worker_id: str
    processing_time_ms: int
    error: str | None = None

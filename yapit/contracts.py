"""Contracts for Redis keys, queues, and job processing."""

import uuid
from typing import Annotated, Final, Literal

import annotated_types
from pydantic import BaseModel, ConfigDict, Field

TTS_INFLIGHT: Final[str] = "tts:inflight:{hash}"
TTS_CURSOR: Final[str] = "tts:cursor:{user_id}:{document_id}"

FILTER_STATUS: Final[str] = "filters:{document_id}:status"
FILTER_CANCEL: Final[str] = "filters:{document_id}:cancel"
FILTER_INFLIGHT: Final[str] = "filters:{document_id}:inflight"


SynthesisMode = Literal["browser", "server"]


def get_queue_name(model: str) -> str:
    """Queue name for server-side synthesis. Browser mode doesn't use queues."""
    return f"tts:queue:{model}"


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
    """JSON contract between gateway and worker."""

    job_id: uuid.UUID
    variant_hash: str
    user_id: str
    document_id: uuid.UUID
    block_idx: int

    synthesis_parameters: SynthesisParameters

    model_config = ConfigDict(frozen=True)


class SynthesisResult(BaseModel):
    job_id: uuid.UUID
    audio: Annotated[bytes, annotated_types.MaxLen(10 * 1024 * 1024)]
    duration_ms: int
    # For HIGGS context accumulation: base64-encoded serialized audio token tensor from this block
    audio_tokens: str | None = None


# WebSocket messages: Client → Server


class WSSynthesizeRequest(BaseModel):
    type: Literal["synthesize"] = "synthesize"
    document_id: uuid.UUID
    block_indices: list[int]
    cursor: int
    model: str
    voice: str
    synthesis_mode: SynthesisMode


class WSCursorMoved(BaseModel):
    type: Literal["cursor_moved"] = "cursor_moved"
    document_id: uuid.UUID
    cursor: int


# WebSocket messages: Server → Client

BlockStatus = Literal["queued", "processing", "cached", "skipped", "error"]


class WSBlockStatus(BaseModel):
    type: Literal["status"] = "status"
    document_id: uuid.UUID
    block_idx: int
    status: BlockStatus
    audio_url: str | None = None
    error: str | None = None


class WSEvicted(BaseModel):
    type: Literal["evicted"] = "evicted"
    document_id: uuid.UUID
    block_indices: list[int]

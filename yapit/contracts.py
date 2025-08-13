"""Contracts for Redis keys, queues, and job processing."""

import uuid
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

# TTS-related keys
TTS_INFLIGHT: Final[str] = "tts:inflight:{hash}"  # redis NX lock

# Filter-related keys (one filter-job per document)
FILTER_STATUS: Final[str] = "filters:{document_id}:status"  # pending | running | done | error
FILTER_CANCEL: Final[str] = "filters:{document_id}:cancel"  # set -> worker aborts ASAP
FILTER_INFLIGHT: Final[str] = "filters:{document_id}:inflight"  # redis NX lock


def get_queue_name(model_slug: str) -> str:
    return f"tts:queue:{model_slug}"


class SynthesisParameters(BaseModel):
    """Parameters for TTS synthesis."""

    model_slug: str
    voice_slug: str
    text: str
    codec: str  # codec the worker must produce / translate to
    kwargs: dict = Field(default_factory=dict)  # additional parameters for the worker

    model_config = ConfigDict(frozen=True)


class SynthesisJob(BaseModel):
    """JSON contract between gateway and worker."""

    # routing / identity
    job_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    variant_hash: str
    user_id: str  # who to bill for this synthesis

    synthesis_parameters: SynthesisParameters

    model_config = ConfigDict(frozen=True)


class SynthesisResult(BaseModel):
    job_id: uuid.UUID
    audio: bytes
    duration_ms: int

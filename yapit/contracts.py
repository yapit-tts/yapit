"""Contracts for Redis keys, queues, and job processing."""

import uuid
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, computed_field

# TTS-related keys
TTS_AUDIO: Final[str] = "tts:audio:{hash}"  # raw PCM/Opus bytes for a fully rendered block
TTS_DONE: Final[str] = "tts:{hash}:done"  # pubsub stream for completion notification
TTS_INFLIGHT: Final[str] = "tts:inflight:{hash}"  # redis NX lock

# Filter-related keys (one filter-job per document)
FILTER_STATUS: Final[str] = "filters:{document_id}:status"  # pending | running | done | error
FILTER_CANCEL: Final[str] = "filters:{document_id}:cancel"  # set -> worker aborts ASAP
FILTER_INFLIGHT: Final[str] = "filters:{document_id}:inflight"  # redis NX lock


def get_queue_name(model_slug: str) -> str:
    """Get Redis queue name for a model."""
    return f"yapit:queue:{model_slug}"


class SynthesisJob(BaseModel):
    """JSON contract between gateway and worker."""

    # routing / identity
    job_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    variant_hash: str

    # synthesis parameters
    model_slug: str
    voice_slug: str
    text: str
    speed: float
    # codec the worker must produce / translate to
    codec: str

    model_config = ConfigDict(frozen=True)

    @computed_field
    @property
    def done_channel(self) -> str:
        return TTS_DONE.format(hash=self.variant_hash)

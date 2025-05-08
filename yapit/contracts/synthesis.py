import uuid
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, computed_field

from yapit.contracts.redis_keys import TTS_DONE, TTS_STREAM

_JOB_QUEUE_PREFIX: Final[str] = "tts:jobs"


def get_job_queue_name(model_slug: str) -> str:
    """Per-backend list queue."""
    return f"{_JOB_QUEUE_PREFIX}:{model_slug}"


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
    def stream_channel(self) -> str:
        return TTS_STREAM.format(hash=self.variant_hash)

    @computed_field
    @property
    def done_channel(self) -> str:
        return TTS_DONE.format(hash=self.variant_hash)

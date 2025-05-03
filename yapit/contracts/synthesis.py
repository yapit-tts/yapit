import uuid
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

_JOB_QUEUE_PREFIX: Final[str] = "tts:jobs"


def get_job_queue_name(model_slug: str) -> str:
    """Per-backend list queue."""
    return f"{_JOB_QUEUE_PREFIX}:{model_slug}"


class SynthesisJob(BaseModel):
    """JSON contract between gateway and worker."""

    # routing / identity
    job_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    variant_hash: str
    channel: str  # pubsub channel (tts:<variant_id>)

    # synthesis parameters
    model_slug: str
    voice_slug: str
    text: str
    speed: float
    codec: Literal["pcm", "opus"] = "pcm"

    model_config = ConfigDict(frozen=True)

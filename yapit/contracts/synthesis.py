import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def queue_name(model_slug: str, prefix: str = "tts:") -> str:
    """Return the Redis LIST name a job for *model_slug* must be pushed to."""
    return f"{prefix}{model_slug}"


class SynthesisJob(BaseModel):
    """JSON contract between gateway and worker."""

    # routing / identity
    job_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    variant_id: str  # text + audio meta hash
    channel: str  # pubsub channel (tts:<variant_id>)

    # synthesis parameters
    model_slug: str
    voice_slug: str
    text: str
    speed: float
    codec: Literal["pcm", "opus"] = "pcm"

    model_config = ConfigDict(frozen=True)

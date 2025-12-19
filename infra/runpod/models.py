"""RunPod infrastructure models."""

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class RunPodTemplate:
    name: str
    imageName: str
    containerDiskInGb: int
    env: dict[str, str] | None = None
    dockerStartCmd: list[str] | None = None
    isServerless: bool = True
    isPublic: bool = False

    def to_api_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return {k: v for k, v in data.items() if v is not None}


@dataclass
class RunPodEndpoint:
    name: str
    templateId: str
    workersMin: int
    workersMax: int
    # GPU config
    gpuTypeIds: list[str] | None = None
    gpuCount: int = 1
    # Model caching (HuggingFace URL, cached at /runpod-volume/huggingface-cache/)
    model: str | None = None
    # Scaling
    scalerType: str = "QUEUE_DELAY"
    scalerValue: int = 4
    idleTimeout: int = 5


@dataclass
class EndpointConfig:
    template: RunPodTemplate
    endpoint: RunPodEndpoint

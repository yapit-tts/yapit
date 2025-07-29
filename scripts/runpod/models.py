from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class ContainerRegistryAuth:
    """Container registry authentication credentials."""

    name: str
    username: str
    password: str  # For Docker Hub, use a personal access token
    id: str | None = None  # Set after creation


@dataclass
class RunPodTemplate:
    name: str
    imageName: str  # Docker image (GitHub deployment requires UI/OAuth)
    containerDiskInGb: int
    isServerless: bool = True
    category: str = "NVIDIA"
    isPublic: bool = False
    env: dict[str, str] | None = None
    dockerStartCmd: str | None = None
    dockerEntrypoint: str | None = None
    volumeInGb: int | None = None
    volumeMountPath: str | None = None
    ports: list[dict[str, Any]] | None = None
    containerRegistryAuthId: str | None = None

    def to_api_dict(self) -> dict[str, Any]:
        """Convert to API-compatible dict, removing None values."""
        data = asdict(self)
        return {k: v for k, v in data.items() if v is not None}


@dataclass
class RunPodEndpoint:
    name: str
    templateId: str
    gpuTypeIds: list[str]
    workersMin: int = 0
    workersMax: int = 1
    scalerType: str = "QUEUE_DELAY"
    scalerValue: int = 5
    executionTimeoutMs: int = 60000
    idleTimeout: int | None = None
    flashboot: bool = False
    gpuCount: int = 1
    vcpuCount: int | None = None
    memoryInGb: int | None = None
    volumeInGb: int | None = None
    networkVolumeId: str | None = None
    dataCenterIds: list[str] | None = None
    cpuFlavorIds: list[str] | None = None
    allowedCudaVersions: list[str] | None = None

    def to_api_dict(self) -> dict[str, Any]:
        """Convert to API-compatible dict, removing None values."""
        data = asdict(self)
        # Remove templateId from the dict as it's not part of the endpoint creation payload
        data.pop("templateId", None)
        return {k: v for k, v in data.items() if v is not None}


@dataclass
class EndpointConfig:
    """Complete configuration for a RunPod endpoint."""

    template: RunPodTemplate
    endpoint: RunPodEndpoint

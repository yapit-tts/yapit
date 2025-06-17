"""Worker ID parsing and conversion utilities."""

from dataclasses import dataclass
from typing import Self


@dataclass(frozen=True)
class WorkerId:
    """Parse and convert worker identifiers.

    Worker IDs use the format: deployment/model/device
    Examples: local/kokoro/cpu, runpod/kokoro/gpu
    """

    deployment: str  # local, runpod
    model: str  # kokoro, dia
    device: str  # cpu, gpu

    @classmethod
    def from_string(cls, worker_id: str) -> Self:
        """Parse worker ID from slash-separated string."""
        parts = worker_id.split("/")
        if len(parts) != 3:
            raise ValueError(f"Invalid worker ID format: '{worker_id}'. Expected format: deployment/model/device")
        return cls(deployment=parts[0], model=parts[1], device=parts[2])

    def to_string(self) -> str:
        """Get the worker ID string format."""
        return f"{self.deployment}/{self.model}/{self.device}"

    def to_slug(self) -> str:
        """Get URL-safe slug for API/database (dash-separated)."""
        return f"{self.deployment}-{self.model}-{self.device}"

    def to_queue_name(self) -> str:
        """Get full Redis queue name."""
        return f"yapit:queue:{self.to_string()}"

    @classmethod
    def from_slug(cls, slug: str) -> Self:
        """Parse from dash-separated slug format."""
        parts = slug.split("-")
        if len(parts) != 3:
            raise ValueError(f"Invalid slug format: '{slug}'. Expected format: deployment-model-device")
        return cls(deployment=parts[0], model=parts[1], device=parts[2])

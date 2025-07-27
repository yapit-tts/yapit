from abc import ABC, abstractmethod


class SynthAdapter(ABC):
    @abstractmethod
    async def initialize(self) -> None: ...

    @abstractmethod
    async def synthesize(self, text: str, **kwargs) -> bytes | str:
        """Synthesize text to pcm audio bytes."""

    @abstractmethod
    def calculate_duration_ms(self, audio_bytes: bytes) -> int:
        """Calculate audio duration in milliseconds from pcm audio bytes."""

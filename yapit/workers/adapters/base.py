from abc import ABC, abstractmethod


class SynthAdapter(ABC):
    @property
    @abstractmethod
    def sample_rate(self) -> int: ...

    @property
    @abstractmethod
    def channels(self) -> int: ...

    @property
    @abstractmethod
    def sample_width(self) -> int: ...

    @property
    @abstractmethod
    def native_codec(self) -> str: ...

    @abstractmethod
    async def initialize(self) -> None: ...

    @abstractmethod
    async def synthesize(self, text: str, *, voice: str, speed: float) -> bytes:
        """Synthesize text to pcm audio bytes."""

    def calculate_duration_ms(self, audio_bytes: bytes) -> int:
        """Calculate audio duration in milliseconds from pcm audio bytes."""
        return int(len(audio_bytes) / (self.sample_rate * self.channels * self.sample_width) * 1000)

from abc import ABC, abstractmethod
from typing import TypedDict, Unpack


class SynthAdapter[SynthesisParameters: TypedDict](ABC):
    @abstractmethod
    async def initialize(self) -> None: ...

    @abstractmethod
    async def synthesize(self, text: str, **kwargs: Unpack[SynthesisParameters]) -> bytes | str:
        """Synthesize text to pcm audio bytes."""

    @abstractmethod
    def calculate_duration_ms(self, audio_bytes: bytes) -> int:
        """Calculate audio duration in milliseconds from pcm audio bytes."""

    def get_word_timestamps(self) -> list[dict] | None:
        """Word-level timestamps from last synthesis, or None if unsupported."""
        return None

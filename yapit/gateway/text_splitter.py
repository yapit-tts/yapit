import abc
import re
from enum import StrEnum, auto
from functools import lru_cache

from pydantic import BaseModel, Field


class TextSplitterConfig(BaseModel):
    max_chars: int = Field(default=1000, gt=0)


class TextSplitter(abc.ABC):
    def __init__(self, config: TextSplitterConfig):
        self.config = config

    @abc.abstractmethod
    def split(self, text: str) -> list[str]:
        """Splits input text into a list of smaller text blocks.

        Args:
            text: The input text string to be split.

        Returns:
            A list of text block strings.
        """


class DummySplitter(TextSplitter):
    def split(self, text: str) -> list[str]:
        """Simply splits text into blocks of max_chars_per_block length, disregarding any structure."""
        if not text or not text.strip():
            return []
        blocks = []
        max_length = self.config.max_chars
        current_pos = 0
        text_len = len(text)
        while current_pos < text_len:
            end_pos = min(current_pos + max_length, text_len)
            chunk = text[current_pos:end_pos].strip()
            if chunk:
                blocks.append(chunk)
            current_pos = end_pos
        return blocks


class SimpleSplitter(TextSplitter):
    """Language-agnostic splitter using paragraphs -> sentences -> commas -> words."""

    _DELIMS = [
        (re.compile(r"\n{2,}"), "\n\n"),  # paragraphs
        (re.compile(r"(?<=[.!?])\s+"), " "),  # sentences
        (re.compile(r",\s*"), ", "),  # commas
        (re.compile(r"\s+"), " "),  # words
    ]

    def split(self, text: str) -> list[str]:
        if not text or not text.strip():
            return []
        text = text.strip()
        return self._split_recursive(text, level=0)

    def _split_recursive(self, segment: str, level: int) -> list[str]:
        if len(segment) <= self.config.max_chars:
            return [segment]
        if level >= len(self._DELIMS):
            return self._hard_cut(segment)

        regex, delimiter = self._DELIMS[level]
        blocks: list[str] = []
        current = ""
        for part in regex.split(segment):
            if not part:
                continue
            # Try appending with delimiter
            to_append = current + delimiter + part if current else part
            if len(to_append) <= self.config.max_chars:
                current = to_append
                continue
            # Flush current
            if current:
                blocks.append(current.rstrip())
                current = ""
            # Handle oversized part
            if len(part) > self.config.max_chars:
                blocks.extend(self._split_recursive(part, level + 1))
            else:
                current = part
        if current:
            blocks.append(current.rstrip())
        return blocks

    def _hard_cut(self, segment: str) -> list[str]:
        blocks: list[str] = []
        start = 0
        while start < len(segment):
            end = min(start + self.config.max_chars, len(segment))
            cut = segment.rfind(" ", start + 1, end)
            if cut == -1 or cut <= start:
                cut = end
            blocks.append(segment[start:cut].rstrip())
            start = cut
        return [b for b in blocks if b]


class TextSplitters(StrEnum):
    DUMMY = auto()
    SIMPLE = auto()


@lru_cache
def get_text_splitter() -> TextSplitter:
    from yapit.gateway.config import get_settings

    settings = get_settings()
    splitter_type = settings.splitter_type.lower()
    splitter = {
        TextSplitters.DUMMY: DummySplitter,
        TextSplitters.SIMPLE: SimpleSplitter,
    }.get(splitter_type)
    if splitter:
        return splitter(settings.splitter_config)
    raise ValueError(
        f"Unknown text splitter type: {splitter_type}. Supported types: {', '.join([s.name for s in TextSplitters])}."
    )

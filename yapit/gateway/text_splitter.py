import abc
import re
from enum import StrEnum, auto

from pydantic import BaseModel, Field


class TextSplitters(StrEnum):
    DUMMY = auto()
    HIERARCHICAL = auto()


class TextSplitterConfig(BaseModel):
    max_chars: int = Field(default=1000, gt=0)


class TextSplitter(abc.ABC):
    def __init__(self, config: TextSplitterConfig):
        self.config = config

    @abc.abstractmethod
    def split(self, text: str) -> list[str]:
        """Splits plain text input into a list of smaller text blocks.

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
        max_length = self.config.max_chars
        return [chunk.strip() for i in range(0, len(text), max_length) if (chunk := text[i : i + max_length].strip())]


class HierarchicalSplitter(TextSplitter):
    """Language-agnostic splitter using paragraphs -> sentences -> commas -> words."""

    _DELIMS = [
        (re.compile(r"\n{2,}"), "\n\n"),  # paragraphs
        (re.compile(r"(?<=[.!?])\s+"), " "),  # sentences
        (re.compile(r",\s*"), ", "),  # commas
        (re.compile(r"\s+"), " "),  # words
    ]

    def split(self, text: str) -> list[str]:
        return self._split_recursive(text.strip(), 0) if text and text.strip() else []

    def _split_recursive(self, segment: str, level: int) -> list[str]:
        if len(segment) <= self.config.max_chars:
            return [segment]
        if level >= len(self._DELIMS):
            return self._hard_cut(segment)

        regex, delimiter = self._DELIMS[level]
        blocks, current = [], ""
        for part in filter(None, regex.split(segment)):  # None filters all falsy (empty strings)
            to_append = f"{current}{delimiter}{part}" if current else part
            if len(to_append) <= self.config.max_chars:
                current = to_append
            else:
                if current:
                    blocks.append(current.rstrip())
                    current = ""
                blocks.extend(self._split_recursive(part, level + 1) if len(part) > self.config.max_chars else [part])
        return blocks + [current.rstrip()] if current else blocks

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

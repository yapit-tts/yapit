import abc

from pydantic import BaseModel  # Alias to avoid clash
from pydantic import Field as PydanticField


class TextSplitterConfig(BaseModel):
    """Configuration settings for text splitters."""

    max_chars_per_block: int = PydanticField(1000, gt=0)


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
        max_length = self.config.max_chars_per_block
        current_pos = 0
        text_len = len(text)
        while current_pos < text_len:
            end_pos = min(current_pos + max_length, text_len)
            chunk = text[current_pos:end_pos].strip()
            if chunk:
                blocks.append(chunk)
            current_pos = end_pos
        return blocks

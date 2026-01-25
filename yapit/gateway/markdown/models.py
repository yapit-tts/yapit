"""Data models for structured document representation.

The core abstraction is AudioChunk - a piece of text with an audio block index.
All blocks that produce audio have a list of AudioChunks, enabling uniform
splitting and indexing across paragraphs, list items, image captions, etc.
"""

from typing import Literal

from pydantic import BaseModel, Field

# === AUDIO ===


class AudioChunk(BaseModel):
    """A chunk of text for TTS synthesis."""

    text: str
    audio_block_idx: int


# === INLINE CONTENT (AST) ===


class TextContent(BaseModel):
    type: Literal["text"] = "text"
    content: str


class CodeSpanContent(BaseModel):
    type: Literal["code_span"] = "code_span"
    content: str


class StrongContent(BaseModel):
    type: Literal["strong"] = "strong"
    content: list["InlineContent"]


class EmphasisContent(BaseModel):
    type: Literal["emphasis"] = "emphasis"
    content: list["InlineContent"]


class LinkContent(BaseModel):
    type: Literal["link"] = "link"
    href: str
    title: str | None = None
    content: list["InlineContent"]


class InlineImageContent(BaseModel):
    type: Literal["inline_image"] = "inline_image"
    src: str
    alt: str


class MathInlineContent(BaseModel):
    type: Literal["math_inline"] = "math_inline"
    content: str  # LaTeX


InlineContent = (
    TextContent
    | CodeSpanContent
    | StrongContent
    | EmphasisContent
    | LinkContent
    | InlineImageContent
    | MathInlineContent
)


# === BLOCK TYPES ===


class HeadingBlock(BaseModel):
    type: Literal["heading"] = "heading"
    id: str
    level: Literal[1, 2, 3, 4, 5, 6]
    html: str
    ast: list[InlineContent]
    audio_chunks: list[AudioChunk] = Field(default_factory=list)


class ParagraphBlock(BaseModel):
    type: Literal["paragraph"] = "paragraph"
    id: str
    html: str  # Contains <span data-audio-idx="N"> wrappers if split
    ast: list[InlineContent]
    audio_chunks: list[AudioChunk] = Field(default_factory=list)


class CodeBlock(BaseModel):
    type: Literal["code"] = "code"
    id: str
    language: str | None = None
    content: str
    audio_chunks: list[AudioChunk] = Field(default_factory=list)  # Always empty


class MathBlock(BaseModel):
    type: Literal["math"] = "math"
    id: str
    content: str  # LaTeX
    display_mode: bool = True
    audio_chunks: list[AudioChunk] = Field(default_factory=list)


class TableBlock(BaseModel):
    type: Literal["table"] = "table"
    id: str
    headers: list[str]
    rows: list[list[str]]
    audio_chunks: list[AudioChunk] = Field(default_factory=list)  # Always empty


class ThematicBreak(BaseModel):
    type: Literal["hr"] = "hr"
    id: str
    audio_chunks: list[AudioChunk] = Field(default_factory=list)  # Always empty


class ListItem(BaseModel):
    html: str  # Contains <span data-audio-idx="N"> wrappers if split
    ast: list[InlineContent]
    audio_chunks: list[AudioChunk] = Field(default_factory=list)


class ListBlock(BaseModel):
    type: Literal["list"] = "list"
    id: str
    ordered: bool
    start: int | None = None
    items: list[ListItem]
    audio_chunks: list[AudioChunk] = Field(default_factory=list)  # Always empty (items have chunks)


class ImageBlock(BaseModel):
    type: Literal["image"] = "image"
    id: str
    src: str
    alt: str
    caption: str | None = None  # Display caption (with LaTeX)
    caption_html: str | None = None  # Caption with span wrappers if split
    title: str | None = None
    width_pct: float | None = None
    row_group: str | None = None
    audio_chunks: list[AudioChunk] = Field(default_factory=list)


class BlockquoteBlock(BaseModel):
    type: Literal["blockquote"] = "blockquote"
    id: str
    blocks: list["ContentBlock"]
    audio_chunks: list[AudioChunk] = Field(default_factory=list)  # Always empty (nested blocks have chunks)


ContentBlock = (
    HeadingBlock
    | ParagraphBlock
    | CodeBlock
    | MathBlock
    | TableBlock
    | ThematicBreak
    | ListBlock
    | ImageBlock
    | BlockquoteBlock
)

# Update forward references
HeadingBlock.model_rebuild()
ParagraphBlock.model_rebuild()
CodeBlock.model_rebuild()
MathBlock.model_rebuild()
TableBlock.model_rebuild()
ThematicBreak.model_rebuild()
ListBlock.model_rebuild()
ImageBlock.model_rebuild()
BlockquoteBlock.model_rebuild()


# === DOCUMENT ===


class StructuredDocument(BaseModel):
    """The full structured representation of a markdown document."""

    version: str = "1.0"
    blocks: list[ContentBlock]

    def get_audio_blocks(self) -> list[str]:
        """Get list of text content for audio blocks, in order.

        Returns a flat list of strings indexed by audio_block_idx.
        Collects from all blocks and nested structures (list items, blockquotes).
        """
        # Collect all chunks with their indices
        all_chunks: list[tuple[int, str]] = []

        def collect_from_block(block: ContentBlock) -> None:
            # Direct audio chunks on the block
            for chunk in block.audio_chunks:
                all_chunks.append((chunk.audio_block_idx, chunk.text))

            # Nested structures
            if isinstance(block, ListBlock):
                for item in block.items:
                    for chunk in item.audio_chunks:
                        all_chunks.append((chunk.audio_block_idx, chunk.text))

            if isinstance(block, BlockquoteBlock):
                for nested in block.blocks:
                    collect_from_block(nested)

        for block in self.blocks:
            collect_from_block(block)

        # Sort by index and return texts
        all_chunks.sort(key=lambda x: x[0])
        return [text for _, text in all_chunks]

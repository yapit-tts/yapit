"""Pydantic models for structured document format.

These models define the JSON schema for parsed markdown documents,
used for frontend rendering and TTS block mapping.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

# === INLINE CONTENT (AST for prose blocks) ===


class TextContent(BaseModel):
    type: Literal["text"] = "text"
    content: str


class StrongContent(BaseModel):
    type: Literal["strong"] = "strong"
    content: list["InlineContent"]


class EmphasisContent(BaseModel):
    type: Literal["emphasis"] = "emphasis"
    content: list["InlineContent"]


class CodeSpanContent(BaseModel):
    type: Literal["code"] = "code"
    content: str


class LinkContent(BaseModel):
    type: Literal["link"] = "link"
    href: str
    title: str | None = None
    content: list["InlineContent"]


class InlineImageContent(BaseModel):
    type: Literal["image"] = "image"
    src: str
    alt: str


class MathInlineContent(BaseModel):
    """Inline math ($...$). Atomic - never split.

    If alt is present, it's used for TTS. Otherwise math is skipped in TTS.
    """

    type: Literal["math_inline"] = "math_inline"
    content: str  # LaTeX content
    alt: str = ""  # TTS text (e.g., "alpha" for $\alpha$)


InlineContent = Annotated[
    TextContent
    | StrongContent
    | EmphasisContent
    | CodeSpanContent
    | LinkContent
    | InlineImageContent
    | MathInlineContent,
    Field(discriminator="type"),
]


# === BLOCK TYPES ===


class HeadingBlock(BaseModel):
    """Heading (h1-h6). Has audio."""

    type: Literal["heading"] = "heading"
    id: str
    level: Literal[1, 2, 3, 4, 5, 6]
    html: str
    ast: list[InlineContent]
    plain_text: str
    audio_block_idx: int | None = None


class ParagraphBlock(BaseModel):
    """Paragraph of text. Has audio."""

    type: Literal["paragraph"] = "paragraph"
    id: str
    html: str
    ast: list[InlineContent]
    plain_text: str
    audio_block_idx: int | None = None
    visual_group_id: str | None = None  # Groups split sentences from the same paragraph


class ListItem(BaseModel):
    """Single item in a list."""

    html: str
    ast: list[InlineContent]
    plain_text: str
    audio_block_idx: int | None = None


class ListBlock(BaseModel):
    """Ordered or unordered list. Container for items which have their own audio."""

    type: Literal["list"] = "list"
    id: str
    ordered: bool
    start: int | None = None
    items: list[ListItem]
    plain_text: str
    audio_block_idx: None = None


class BlockquoteBlock(BaseModel):
    """Blockquote with nested content. Has audio."""

    type: Literal["blockquote"] = "blockquote"
    id: str
    blocks: list["ContentBlock"]
    plain_text: str
    audio_block_idx: int | None = None


class CodeBlock(BaseModel):
    """Fenced or indented code block. No audio."""

    type: Literal["code"] = "code"
    id: str
    language: str | None = None
    content: str
    audio_block_idx: None = None


class MathBlock(BaseModel):
    """Display math ($$...$$). Has audio if alt text is provided."""

    type: Literal["math"] = "math"
    id: str
    content: str  # LaTeX content
    alt: str = ""  # TTS text (read aloud if present)
    display_mode: bool = True
    audio_block_idx: int | None = None


class TableBlock(BaseModel):
    """Table with headers and rows. No audio."""

    type: Literal["table"] = "table"
    id: str
    headers: list[str]
    rows: list[list[str]]
    audio_block_idx: None = None


class ImageBlock(BaseModel):
    """Standalone image. Has audio if alt or caption is provided."""

    type: Literal["image"] = "image"
    id: str
    src: str
    alt: str = ""  # Descriptive text for TTS (what the image shows)
    caption: str = ""  # Figure caption for TTS and display (e.g., "Figure 2: Results")
    title: str | None = None
    width_pct: float | None = None  # Figure width as % of page (from YOLO bbox)
    row_group: str | None = None  # "row0", "row1", etc. - figures in same row are side-by-side
    audio_block_idx: int | None = None


class ThematicBreak(BaseModel):
    """Horizontal rule. No audio."""

    type: Literal["hr"] = "hr"
    id: str
    audio_block_idx: None = None


ContentBlock = Annotated[
    HeadingBlock
    | ParagraphBlock
    | ListBlock
    | BlockquoteBlock
    | CodeBlock
    | MathBlock
    | TableBlock
    | ImageBlock
    | ThematicBreak,
    Field(discriminator="type"),
]


# === ROOT DOCUMENT ===


class StructuredDocument(BaseModel):
    """Root document containing all content blocks."""

    version: Literal["1.0"] = "1.0"
    blocks: list[ContentBlock]

    def get_audio_blocks(self) -> list[str]:
        """Extract plain_text from blocks that have audio (prose only).

        Recurses into container blocks (blockquotes) to collect nested audio.
        """
        result = []
        self._collect_audio_blocks(self.blocks, result)
        return result

    def _collect_audio_blocks(self, blocks: list["ContentBlock"], result: list[str]) -> None:
        """Recursively collect audio blocks."""
        for block in blocks:
            if block.type == "blockquote":
                self._collect_audio_blocks(block.blocks, result)
            elif block.type == "list":
                for item in block.items:
                    if item.audio_block_idx is not None:
                        result.append(item.plain_text)
            elif block.type == "math" and block.audio_block_idx is not None:
                result.append(block.alt)
            elif block.type == "image" and block.audio_block_idx is not None:
                # Combine alt and caption for TTS
                parts = [p for p in (block.alt, block.caption) if p]
                result.append(" ".join(parts))
            elif block.audio_block_idx is not None:
                result.append(block.plain_text)


# Rebuild models to resolve forward references
StrongContent.model_rebuild()
EmphasisContent.model_rebuild()
LinkContent.model_rebuild()
BlockquoteBlock.model_rebuild()

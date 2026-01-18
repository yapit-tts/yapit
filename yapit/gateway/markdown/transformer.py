"""Transform markdown AST to StructuredDocument.

Walks the markdown-it-py SyntaxTreeNode and produces our structured JSON format
with both HTML and AST representations for prose blocks.
"""

import re
from typing import Literal, cast
from urllib.parse import parse_qs, urlparse

from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode
from mdit_py_plugins.dollarmath import dollarmath_plugin

from yapit.gateway.markdown.models import (
    BlockquoteBlock,
    CodeBlock,
    CodeSpanContent,
    ContentBlock,
    EmphasisContent,
    HeadingBlock,
    ImageBlock,
    InlineContent,
    InlineImageContent,
    LinkContent,
    ListBlock,
    ListItem,
    MathBlock,
    MathInlineContent,
    ParagraphBlock,
    StrongContent,
    StructuredDocument,
    TableBlock,
    TextContent,
    ThematicBreak,
)

# Patterns for yap annotation tags
_YAP_ALT_OPEN = "<yap-alt>"
_YAP_ALT_CLOSE = "</yap-alt>"
_YAP_CAP_OPEN = "<yap-cap>"
_YAP_CAP_CLOSE = "</yap-cap>"


def _is_html_tag(node: SyntaxTreeNode, tag: str) -> bool:
    """Check if node is an html_inline containing the specified tag."""
    return node.type == "html_inline" and node.content == tag


def _extract_yap_alt(children: list[SyntaxTreeNode], start_idx: int) -> tuple[str, int]:
    """Extract <yap-alt>...</yap-alt> starting at start_idx.

    Returns (alt_text, num_nodes_consumed). If no yap-alt found, returns ("", 0).
    """
    if start_idx >= len(children):
        return "", 0

    if not _is_html_tag(children[start_idx], _YAP_ALT_OPEN):
        return "", 0

    # Collect content until </yap-alt>
    alt_parts = []
    i = start_idx + 1
    while i < len(children):
        node = children[i]
        if _is_html_tag(node, _YAP_ALT_CLOSE):
            return "".join(alt_parts), i - start_idx + 1
        elif node.type == "text":
            alt_parts.append(node.content or "")
        # Skip other node types (shouldn't happen in well-formed yap-alt)
        i += 1

    # No closing tag found - malformed, return nothing
    return "", 0


def _extract_yap_cap(children: list[SyntaxTreeNode], start_idx: int) -> tuple[list[SyntaxTreeNode], int]:
    """Extract <yap-cap>...</yap-cap> starting at start_idx.

    Returns (list of nodes inside caption, num_nodes_consumed).
    If no yap-cap found, returns ([], 0).
    """
    if start_idx >= len(children):
        return [], 0

    if not _is_html_tag(children[start_idx], _YAP_CAP_OPEN):
        return [], 0

    # Collect nodes until </yap-cap>
    caption_nodes = []
    i = start_idx + 1
    while i < len(children):
        node = children[i]
        if _is_html_tag(node, _YAP_CAP_CLOSE):
            return caption_nodes, i - start_idx + 1
        caption_nodes.append(node)
        i += 1

    # No closing tag found - malformed, return nothing
    return [], 0


def _extract_plain_text_from_caption_nodes(nodes: list[SyntaxTreeNode]) -> tuple[str, str]:
    """Extract display text and TTS text from caption nodes.

    Handles <yap-alt> within captions for math alt text.
    Returns (display_text, tts_text) where:
    - display_text: includes math LaTeX for rendering
    - tts_text: replaces math with alt text for speech
    """
    display_parts = []
    tts_parts = []
    i = 0
    while i < len(nodes):
        node = nodes[i]

        if node.type == "math_inline":
            # Check if followed by <yap-alt>
            alt, consumed = _extract_yap_alt(nodes, i + 1)
            display_parts.append(f"${node.content}$")
            tts_parts.append(alt if alt else node.content or "")
            i += 1 + consumed
        elif node.type == "text":
            display_parts.append(node.content or "")
            tts_parts.append(node.content or "")
            i += 1
        elif _is_html_tag(node, _YAP_ALT_OPEN):
            # Orphaned yap-alt (not after math) - skip it
            _, consumed = _extract_yap_alt(nodes, i)
            i += consumed if consumed else 1
        else:
            # Other nodes - include content if any
            if node.content:
                display_parts.append(node.content)
                tts_parts.append(node.content)
            i += 1

    return "".join(display_parts), "".join(tts_parts)


class DocumentTransformer:
    """Transforms markdown AST to StructuredDocument."""

    def __init__(
        self,
        max_block_chars: int,
        soft_limit_mult: float,
        min_chunk_size: int,
    ):
        self.max_block_chars = max_block_chars
        self.soft_limit_mult = soft_limit_mult
        self.min_chunk_size = min_chunk_size
        self._block_counter = 0
        self._audio_idx_counter = 0
        self._visual_group_counter = 0
        self._md = self._create_renderer()
        # Annotations extracted from AST (node_id -> alt text)
        self._math_block_alts: dict[int, str] = {}

    def _create_renderer(self) -> MarkdownIt:
        """Create markdown renderer for HTML output."""
        md = MarkdownIt("commonmark")
        md.enable("table")
        md.enable("strikethrough")
        dollarmath_plugin(md)
        return md

    def _next_block_id(self) -> str:
        id_ = f"b{self._block_counter}"
        self._block_counter += 1
        return id_

    def _next_audio_idx(self, plain_text: str) -> int | None:
        """Get next audio block index, or None if text is empty/unspeakable."""
        if not plain_text.strip():
            return None
        idx = self._audio_idx_counter
        self._audio_idx_counter += 1
        return idx

    def _next_visual_group_id(self) -> str:
        id_ = f"vg{self._visual_group_counter}"
        self._visual_group_counter += 1
        return id_

    def transform(self, ast: SyntaxTreeNode) -> StructuredDocument:
        """Transform AST root to StructuredDocument."""
        self._block_counter = 0
        self._audio_idx_counter = 0
        self._visual_group_counter = 0
        self._math_block_alts = {}
        # Pre-process: extract {alt} annotations for math_blocks
        self._extract_math_block_annotations(ast)
        blocks = self._transform_children(ast)
        return StructuredDocument(blocks=blocks)

    def _extract_math_block_annotations(self, ast: SyntaxTreeNode) -> None:
        """Extract <yap-alt> annotations from paragraphs following math_blocks.

        When display math ($$...$$) is followed by a paragraph containing only
        <yap-alt>...</yap-alt>, we extract the alt text and mark that paragraph for skipping.
        """
        children = ast.children
        skip_indices: set[int] = set()

        for i, child in enumerate(children):
            if child.type == "math_block" and i + 1 < len(children):
                next_child = children[i + 1]
                # Check if next is a paragraph with just <yap-alt>...</yap-alt>
                if next_child.type == "paragraph" and next_child.children:
                    inline = next_child.children[0]
                    if inline.type == "inline" and inline.children:
                        # Look for <yap-alt>...</yap-alt> pattern
                        alt, consumed = _extract_yap_alt(inline.children, 0)
                        if alt and consumed == len(inline.children):
                            # Entire inline is just the yap-alt annotation
                            self._math_block_alts[id(child)] = alt
                            skip_indices.add(i + 1)

        # Store indices to skip during transform
        self._skip_child_indices = skip_indices

    def _transform_children(self, node: SyntaxTreeNode) -> list[ContentBlock]:
        """Transform all children of a node."""
        blocks: list[ContentBlock] = []
        for i, child in enumerate(node.children):
            # Skip paragraphs that were consumed as {alt} annotations
            if i in getattr(self, "_skip_child_indices", set()):
                continue
            blocks.extend(self._transform_node(child))
        return blocks

    def _transform_node(self, node: SyntaxTreeNode) -> list[ContentBlock]:
        """Transform a single AST node to ContentBlock(s).

        Returns a list because large blocks may be split into multiple.
        """
        handlers = {
            "heading": self._transform_heading,
            "paragraph": self._transform_paragraph,
            "fence": self._transform_code,
            "code_block": self._transform_code,
            "bullet_list": self._transform_list,
            "ordered_list": self._transform_list,
            "blockquote": self._transform_blockquote,
            "table": self._transform_table,
            "hr": self._transform_hr,
            "math_block": self._transform_math,
        }

        handler = handlers.get(node.type)
        if handler:
            return handler(node)

        # Skip unknown node types
        return []

    # === PROSE BLOCKS (with audio) ===

    def _transform_heading(self, node: SyntaxTreeNode) -> list[HeadingBlock]:
        """Transform heading node."""
        level = cast(Literal[1, 2, 3, 4, 5, 6], int(node.tag[1]))  # h1 -> 1, h2 -> 2, etc.
        inline = node.children[0] if node.children else None

        html = self._render_inline_html(inline)
        ast = self._transform_inline(inline)
        plain_text = self._extract_plain_text(inline)

        return [
            HeadingBlock(
                id=self._next_block_id(),
                level=level,
                html=html,
                ast=ast,
                plain_text=plain_text,
                audio_block_idx=self._next_audio_idx(plain_text),
            )
        ]

    def _transform_paragraph(self, node: SyntaxTreeNode) -> list[ContentBlock]:
        """Transform paragraph node, detecting standalone images or splitting if too long."""
        inline = node.children[0] if node.children else None

        # Check for standalone image (paragraph containing only an image)
        if self._is_standalone_image(inline):
            return [self._create_image_block(inline)]

        plain_text = self._extract_plain_text(inline)

        # Check if splitting is needed
        if len(plain_text) <= self.max_block_chars:
            html = self._render_inline_html(inline)
            ast = self._transform_inline(inline)
            return [
                ParagraphBlock(
                    id=self._next_block_id(),
                    html=html,
                    ast=ast,
                    plain_text=plain_text,
                    audio_block_idx=self._next_audio_idx(plain_text),
                )
            ]

        # Split large paragraphs
        return self._split_paragraph(inline, plain_text)

    def _is_standalone_image(self, inline: SyntaxTreeNode | None) -> bool:
        """Check if inline content is just a single image (no other meaningful content).

        Allows <yap-cap>...</yap-cap> and <yap-alt>...</yap-alt> after the image.
        """
        if not inline or not inline.children:
            return False

        # Filter out whitespace-only text, line breaks, and yap annotation tags/content
        children = inline.children
        yap_depth = 0  # Track nesting depth of yap tags
        meaningful = []

        for c in children:
            # Track entry/exit of yap tags (use depth for nested tags)
            if c.type == "html_inline":
                content = c.content or ""
                if content in (_YAP_CAP_OPEN, _YAP_ALT_OPEN):
                    yap_depth += 1
                    continue
                elif content in (_YAP_CAP_CLOSE, _YAP_ALT_CLOSE):
                    yap_depth = max(0, yap_depth - 1)
                    continue

            # Skip content inside yap tags
            if yap_depth > 0:
                continue

            # Skip whitespace and breaks
            if c.type in ("softbreak", "hardbreak"):
                continue
            if c.type == "text" and not (c.content or "").strip():
                continue

            meaningful.append(c)

        return len(meaningful) == 1 and meaningful[0].type == "image"

    def _create_image_block(self, inline: SyntaxTreeNode) -> ImageBlock:
        """Create an ImageBlock from a standalone image paragraph."""
        # Find the image node
        children = inline.children
        img_idx = next(i for i, c in enumerate(children) if c.type == "image")
        img_node = children[img_idx]

        src = img_node.attrs.get("src", "")
        alt = img_node.content or ""
        title = img_node.attrs.get("title")

        # Extract caption from <yap-cap>...</yap-cap> following the image
        caption = ""
        caption_tts = ""
        caption_nodes, _ = _extract_yap_cap(children, img_idx + 1)
        if caption_nodes:
            caption, caption_tts = _extract_plain_text_from_caption_nodes(caption_nodes)

        # Parse layout metadata from URL query params
        width_pct, row_group = self._parse_image_metadata(src)

        # Strip query params from src for clean URL
        clean_src = src.split("?")[0] if "?" in src else src

        # TTS: use caption_tts if available (math replaced with alt), else caption, else alt
        tts_text = caption_tts if caption_tts else (caption if caption else alt)

        return ImageBlock(
            id=self._next_block_id(),
            src=clean_src,
            alt=alt,
            caption=caption,
            title=title,
            width_pct=width_pct,
            row_group=row_group,
            audio_block_idx=self._next_audio_idx(tts_text),
        )

    def _parse_image_metadata(self, src: str) -> tuple[float | None, str | None]:
        """Parse width_pct and row_group from image URL query params."""
        parsed = urlparse(src)
        params = parse_qs(parsed.query)

        width_pct = None
        if "w" in params:
            try:
                width_pct = float(params["w"][0])
            except (ValueError, IndexError):
                pass

        row_group = params.get("row", [None])[0]

        return width_pct, row_group

    def _split_paragraph(self, inline: SyntaxTreeNode | None, plain_text: str) -> list[ParagraphBlock]:
        """Split a large paragraph into multiple blocks at sentence boundaries.

        Preserves inline formatting (bold, italic, etc.) across splits.
        """
        # Get chunk boundaries as character positions
        chunk_ranges = self._get_chunk_ranges(plain_text)

        # Transform full AST once
        full_ast = self._transform_inline(inline)

        blocks = []
        visual_group_id = self._next_visual_group_id()

        for start, end in chunk_ranges:
            # Slice AST to get content for this chunk
            chunk_ast = self._slice_ast(full_ast, start, end)
            chunk_text = plain_text[start:end].strip()
            chunk_html = self._render_ast_to_html(chunk_ast)

            blocks.append(
                ParagraphBlock(
                    id=self._next_block_id(),
                    html=chunk_html,
                    ast=chunk_ast,
                    plain_text=chunk_text,
                    audio_block_idx=self._next_audio_idx(chunk_text),
                    visual_group_id=visual_group_id,
                )
            )

        return blocks

    # Pause pattern: clause separators optionally followed by closing quotes/parens
    # This ensures we don't orphan closing punctuation at the start of the next chunk
    # Includes straight quotes, curly quotes (U+201C/D, U+2018/9), parens, brackets
    _PAUSE_PATTERN = re.compile(r"[,—:;][\"')\]\u201c\u201d\u2018\u2019]?")

    def _get_chunk_ranges(self, text: str) -> list[tuple[int, int]]:
        """Get (start, end) character ranges for each chunk.

        Splitting strategy (in order of preference):
        1. Sentence boundaries (.!?)
        2. Clause separators (,—:;) - when sentences are too long
        3. Word boundaries - last resort for very long clauses
        """
        sentences = re.split(r"(?<=[.!?])\s+", text)

        soft_max = int(self.max_block_chars * self.soft_limit_mult)
        min_chunk_size = self.min_chunk_size

        ranges: list[tuple[int, int]] = []
        current_start = 0
        current_end = 0

        pos = 0
        for sentence in sentences:
            if not sentence.strip():
                continue

            # Find where this sentence starts in the original text
            sent_start = text.find(sentence, pos)
            if sent_start == -1:
                sent_start = pos
            sent_end = sent_start + len(sentence)
            pos = sent_end

            # Check if this sentence alone exceeds the soft limit
            if len(sentence) > soft_max:
                # Flush current chunk if any
                if current_end > current_start:
                    ranges.append((current_start, current_end))
                # Split the long sentence at natural pause points
                self._split_long_sentence(sentence, sent_start, ranges, min_chunk_size)
                current_start = sent_end
                current_end = sent_end
                continue

            # Check if adding this sentence would exceed limit
            potential_end = sent_end
            potential_len = potential_end - current_start
            if potential_len <= self.max_block_chars:
                current_end = potential_end
            else:
                # Flush current chunk and start new one
                if current_end > current_start:
                    ranges.append((current_start, current_end))
                current_start = sent_start
                current_end = sent_end

        # Flush remaining
        if current_end > current_start:
            ranges.append((current_start, current_end))

        return ranges if ranges else [(0, len(text))]

    def _split_long_sentence(
        self, sentence: str, sent_start: int, ranges: list[tuple[int, int]], min_chunk_size: int
    ) -> None:
        """Split a long sentence at natural pause points, falling back to word boundaries."""
        # Find all pause points (comma, m-dash, colon, semicolon)
        pause_matches = list(self._PAUSE_PATTERN.finditer(sentence))
        # Positions after the pause character (where next clause starts, after stripping space)
        pause_positions = [m.end() for m in pause_matches]

        chunk_pos = 0
        while chunk_pos < len(sentence):
            remaining = len(sentence) - chunk_pos
            if remaining <= self.max_block_chars:
                # Remaining text fits in one chunk
                ranges.append((sent_start + chunk_pos, sent_start + len(sentence)))
                break

            # Look for a natural pause point
            split_pos = self._find_pause_split(sentence, chunk_pos, pause_positions, min_chunk_size)

            if split_pos is not None:
                # Split at the pause point (include the pause char, trim trailing space)
                ranges.append((sent_start + chunk_pos, sent_start + split_pos))
                # Skip whitespace after the pause
                chunk_pos = split_pos
                while chunk_pos < len(sentence) and sentence[chunk_pos] == " ":
                    chunk_pos += 1
            else:
                # Fall back to word boundary split
                target_end = min(chunk_pos + self.max_block_chars, len(sentence))
                if target_end < len(sentence):
                    boundary = sentence.rfind(" ", chunk_pos, target_end)
                    if boundary > chunk_pos:
                        # Check if this would leave a tiny orphan
                        orphan_len = len(sentence) - (boundary + 1)
                        if orphan_len < min_chunk_size:
                            # Include the orphan rather than creating a bad split
                            target_end = len(sentence)
                        else:
                            target_end = boundary + 1
                ranges.append((sent_start + chunk_pos, sent_start + target_end))
                chunk_pos = target_end

    def _find_pause_split(
        self, sentence: str, chunk_pos: int, pause_positions: list[int], min_chunk_size: int
    ) -> int | None:
        """Find the best pause point to split at, or None if none suitable.

        Prefers pause points that:
        1. Are within max_block_chars from chunk_pos
        2. Leave at least min_chunk_size chars for the next chunk (avoid tiny orphans)
        3. Are as late as possible (to keep more text together)
        """
        best_pos = None
        remaining = len(sentence) - chunk_pos

        for pos in pause_positions:
            if pos <= chunk_pos:
                continue
            chunk_len = pos - chunk_pos
            next_chunk_len = remaining - chunk_len

            # Skip if this chunk would be too long
            if chunk_len > self.max_block_chars:
                continue

            # Skip if this would leave a tiny orphan (unless it's the only option)
            if next_chunk_len < min_chunk_size and next_chunk_len > 0:
                # Only consider this if we have no better option
                if best_pos is None:
                    best_pos = pos
                continue

            # This is a valid split point - prefer later ones
            best_pos = pos

        return best_pos

    def _slice_ast(self, ast: list[InlineContent], start: int, end: int) -> list[InlineContent]:
        """Slice AST to extract content between character positions.

        Handles nested formatting - if a split falls inside a bold/italic span,
        the span is properly closed in the first chunk and reopened in the second.
        """
        result: list[InlineContent] = []
        pos = 0

        for node in ast:
            node_len = self._get_inline_length(node)
            node_end = pos + node_len

            # Skip nodes entirely before our range
            if node_end <= start:
                pos = node_end
                continue

            # Stop if we're past our range
            if pos >= end:
                break

            # Calculate overlap
            overlap_start = max(0, start - pos)
            overlap_end = min(node_len, end - pos)

            # Slice the node
            sliced = self._slice_inline_node(node, overlap_start, overlap_end)
            if sliced:
                result.extend(sliced)

            pos = node_end

        return result

    def _slice_inline_node(self, node: InlineContent, start: int, end: int) -> list[InlineContent]:
        """Slice a single inline node at given character positions."""
        if node.type == "text":
            content = node.content[start:end]
            return [TextContent(content=content)] if content else []

        elif node.type == "code":
            content = node.content[start:end]
            return [CodeSpanContent(content=content)] if content else []

        elif node.type == "strong":
            inner = self._slice_ast(node.content, start, end)
            return [StrongContent(content=inner)] if inner else []

        elif node.type == "emphasis":
            inner = self._slice_ast(node.content, start, end)
            return [EmphasisContent(content=inner)] if inner else []

        elif node.type == "link":
            inner = self._slice_ast(node.content, start, end)
            if inner:
                return [LinkContent(href=node.href, title=node.title, content=inner)]
            return []

        elif node.type == "image":
            # Images are atomic - include fully or not at all
            return [node] if start == 0 else []

        elif node.type == "math_inline":
            # Math is atomic - include fully or not at all
            return [node] if start == 0 else []

        return []

    def _get_inline_length(self, node: InlineContent) -> int:
        """Get the plain text length of an inline node."""
        if node.type == "text":
            return len(node.content)
        elif node.type == "code":
            return len(node.content)
        elif node.type in ("strong", "emphasis", "link"):
            return sum(self._get_inline_length(child) for child in node.content)
        elif node.type == "image":
            return len(node.alt)
        elif node.type == "math_inline":
            # Math counts toward block length if it has alt text (for TTS)
            return len(node.alt) if node.alt else 0
        return 0

    def _render_ast_to_html(self, ast: list[InlineContent]) -> str:
        """Render our InlineContent AST back to HTML."""
        parts = []
        for node in ast:
            parts.append(self._render_inline_content_html(node))
        return "".join(parts)

    def _render_inline_content_html(self, node: InlineContent) -> str:
        """Render a single InlineContent node to HTML."""
        if node.type == "text":
            return node.content
        elif node.type == "code":
            return f"<code>{node.content}</code>"
        elif node.type == "strong":
            inner = self._render_ast_to_html(node.content)
            return f"<strong>{inner}</strong>"
        elif node.type == "emphasis":
            inner = self._render_ast_to_html(node.content)
            return f"<em>{inner}</em>"
        elif node.type == "link":
            inner = self._render_ast_to_html(node.content)
            title_attr = f' title="{node.title}"' if node.title else ""
            return f'<a href="{node.href}"{title_attr}>{inner}</a>'
        elif node.type == "image":
            return f'<img src="{node.src}" alt="{node.alt}" />'
        elif node.type == "math_inline":
            return f'<span class="math-inline">{node.content}</span>'
        return ""

    def _split_text_into_chunks(self, text: str) -> list[str]:
        """Split text into chunks at sentence boundaries, respecting max_block_chars."""
        # Split at sentence boundaries: . ! ? followed by space or end
        sentences = re.split(r"(?<=[.!?])\s+", text)

        chunks = []
        current_chunk = ""

        for sentence in sentences:
            if not sentence.strip():
                continue

            # If this sentence alone exceeds limit, split it further
            if len(sentence) > self.max_block_chars:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                    current_chunk = ""
                # Hard split at max_block_chars
                for i in range(0, len(sentence), self.max_block_chars):
                    chunks.append(sentence[i : i + self.max_block_chars].strip())
                continue

            # Check if adding this sentence would exceed limit
            test_chunk = f"{current_chunk} {sentence}".strip() if current_chunk else sentence
            if len(test_chunk) <= self.max_block_chars:
                current_chunk = test_chunk
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = sentence

        if current_chunk:
            chunks.append(current_chunk.strip())

        return chunks if chunks else [text]

    def _transform_list(self, node: SyntaxTreeNode) -> list[ListBlock]:
        """Transform list (bullet or ordered) node. Each item gets its own audio index."""
        ordered = node.type == "ordered_list"
        start = cast(int | None, node.attrs.get("start")) if ordered else None

        items = []
        plain_texts = []

        for list_item in node.children:
            item_html_parts = []
            item_ast: list[InlineContent] = []
            item_plain_parts = []

            for child in list_item.children:
                if child.type == "paragraph":
                    inline = child.children[0] if child.children else None
                    item_html_parts.append(self._render_inline_html(inline))
                    item_ast.extend(self._transform_inline(inline))
                    item_plain_parts.append(self._extract_plain_text(inline))
                elif child.type in ("bullet_list", "ordered_list"):
                    nested_html, nested_plain = self._render_list_html(child)
                    item_html_parts.append(nested_html)
                    item_plain_parts.append(nested_plain)

            item_plain_text = " ".join(item_plain_parts)
            items.append(
                ListItem(
                    html=" ".join(item_html_parts),
                    ast=item_ast,
                    plain_text=item_plain_text,
                    audio_block_idx=self._next_audio_idx(item_plain_text),
                )
            )
            plain_texts.append(item_plain_text)

        combined_plain_text = " ".join(plain_texts)
        return [
            ListBlock(
                id=self._next_block_id(),
                ordered=ordered,
                start=start,
                items=items,
                plain_text=combined_plain_text,
            )
        ]

    def _render_list_html(self, node: SyntaxTreeNode) -> tuple[str, str]:
        """Render a list node to HTML and plain text (for nested lists)."""
        ordered = node.type == "ordered_list"
        tag = "ol" if ordered else "ul"
        start_attr = f' start="{node.attrs.get("start")}"' if ordered and node.attrs.get("start") else ""

        items_html = []
        items_plain = []

        for list_item in node.children:
            item_parts_html = []
            item_parts_plain = []

            for child in list_item.children:
                if child.type == "paragraph":
                    inline = child.children[0] if child.children else None
                    item_parts_html.append(self._render_inline_html(inline))
                    item_parts_plain.append(self._extract_plain_text(inline))
                elif child.type in ("bullet_list", "ordered_list"):
                    nested_html, nested_plain = self._render_list_html(child)
                    item_parts_html.append(nested_html)
                    item_parts_plain.append(nested_plain)

            items_html.append(f"<li>{' '.join(item_parts_html)}</li>")
            items_plain.append(" ".join(item_parts_plain))

        html = f"<{tag}{start_attr}>{''.join(items_html)}</{tag}>"
        plain = " ".join(items_plain)
        return html, plain

    def _transform_blockquote(self, node: SyntaxTreeNode) -> list[BlockquoteBlock]:
        """Transform blockquote node.

        Blockquote is a visual container - nested blocks get their own audio indices.
        get_audio_blocks() recurses into blockquote.blocks to collect them.
        """
        inner_blocks = self._transform_children(node)

        plain_texts = []
        for block in inner_blocks:
            if hasattr(block, "plain_text") and block.plain_text:
                plain_texts.append(block.plain_text)

        combined_plain_text = " ".join(plain_texts)
        return [
            BlockquoteBlock(
                id=self._next_block_id(),
                blocks=inner_blocks,
                plain_text=combined_plain_text,
                # No audio_block_idx - it's a container, nested blocks have their own
            )
        ]

    # === NON-PROSE BLOCKS (no audio) ===

    def _transform_code(self, node: SyntaxTreeNode) -> list[CodeBlock]:
        """Transform fenced or indented code block."""
        language = node.info if hasattr(node, "info") and node.info else None
        content = node.content or ""

        return [
            CodeBlock(
                id=self._next_block_id(),
                language=language,
                content=content.rstrip("\n"),
            )
        ]

    def _transform_math(self, node: SyntaxTreeNode) -> list[MathBlock]:
        """Transform math block ($$...$$)."""
        content = node.content or ""
        alt = self._math_block_alts.get(id(node), "")

        return [
            MathBlock(
                id=self._next_block_id(),
                content=content.strip(),
                alt=alt,
                display_mode=True,
                audio_block_idx=self._next_audio_idx(alt),
            )
        ]

    def _transform_table(self, node: SyntaxTreeNode) -> list[TableBlock]:
        """Transform table node."""
        headers: list[str] = []
        rows: list[list[str]] = []

        for child in node.children:
            if child.type == "thead":
                for tr in child.children:
                    for th in tr.children:
                        inline = th.children[0] if th.children else None
                        headers.append(self._render_inline_html(inline))
            elif child.type == "tbody":
                for tr in child.children:
                    row = []
                    for td in tr.children:
                        inline = td.children[0] if td.children else None
                        row.append(self._render_inline_html(inline))
                    rows.append(row)

        return [
            TableBlock(
                id=self._next_block_id(),
                headers=headers,
                rows=rows,
            )
        ]

    def _transform_hr(self, node: SyntaxTreeNode) -> list[ThematicBreak]:
        """Transform horizontal rule."""
        return [ThematicBreak(id=self._next_block_id())]

    # === INLINE CONTENT HELPERS ===

    def _render_inline_html(self, inline: SyntaxTreeNode | None) -> str:
        """Render inline content to HTML string.

        Skips <yap-alt> and <yap-cap> annotation nodes (not for display).
        """
        if not inline or not inline.children:
            return ""

        children = inline.children
        parts = []
        i = 0

        while i < len(children):
            child = children[i]

            # Skip yap-cap sections
            if _is_html_tag(child, _YAP_CAP_OPEN):
                _, consumed = _extract_yap_cap(children, i)
                i += consumed if consumed else 1
                continue

            # Skip yap-alt sections
            if _is_html_tag(child, _YAP_ALT_OPEN):
                _, consumed = _extract_yap_alt(children, i)
                i += consumed if consumed else 1
                continue

            # Skip orphaned closing tags
            if _is_html_tag(child, _YAP_CAP_CLOSE) or _is_html_tag(child, _YAP_ALT_CLOSE):
                i += 1
                continue

            parts.append(self._render_inline_node_html(child))
            i += 1

        return "".join(parts)

    def _render_inline_node_html(self, node: SyntaxTreeNode) -> str:
        """Render a single inline node to HTML."""
        if node.type == "text":
            return node.content or ""
        elif node.type == "strong":
            inner = "".join(self._render_inline_node_html(c) for c in node.children)
            return f"<strong>{inner}</strong>"
        elif node.type == "em":
            inner = "".join(self._render_inline_node_html(c) for c in node.children)
            return f"<em>{inner}</em>"
        elif node.type == "s":  # strikethrough
            inner = "".join(self._render_inline_node_html(c) for c in node.children)
            return f"<s>{inner}</s>"
        elif node.type == "code_inline":
            return f"<code>{node.content or ''}</code>"
        elif node.type == "link":
            href = node.attrs.get("href", "")
            title = node.attrs.get("title", "")
            inner = "".join(self._render_inline_node_html(c) for c in node.children)
            title_attr = f' title="{title}"' if title else ""
            return f'<a href="{href}"{title_attr}>{inner}</a>'
        elif node.type == "image":
            src = node.attrs.get("src", "")
            alt = node.content or ""  # Alt text is in node.content, not attrs['alt']
            title = node.attrs.get("title", "")
            title_attr = f' title="{title}"' if title else ""
            return f'<img src="{src}" alt="{alt}"{title_attr} />'
        elif node.type == "softbreak":
            return " "
        elif node.type == "hardbreak":
            return "<br />"
        elif node.type == "math_inline":
            return f'<span class="math-inline">{node.content or ""}</span>'
        else:
            # Unknown inline type, try to get content
            return node.content or ""

    def _transform_inline(self, inline: SyntaxTreeNode | None) -> list[InlineContent]:
        """Transform inline content to AST representation.

        Extracts <yap-alt> annotations from nodes following math_inline.
        Skips <yap-cap> content (handled separately for images).
        """
        if not inline or not inline.children:
            return []

        children = inline.children
        result: list[InlineContent] = []
        i = 0

        while i < len(children):
            child = children[i]

            # Skip yap-cap sections (handled by _create_image_block)
            if _is_html_tag(child, _YAP_CAP_OPEN):
                _, consumed = _extract_yap_cap(children, i)
                i += consumed if consumed else 1
                continue

            # Skip orphaned yap-alt (shouldn't happen, but be safe)
            if _is_html_tag(child, _YAP_ALT_OPEN):
                _, consumed = _extract_yap_alt(children, i)
                i += consumed if consumed else 1
                continue

            # Skip closing tags that might be orphaned
            if _is_html_tag(child, _YAP_CAP_CLOSE) or _is_html_tag(child, _YAP_ALT_CLOSE):
                i += 1
                continue

            # For math_inline, check for following <yap-alt>
            if child.type == "math_inline":
                alt, consumed = _extract_yap_alt(children, i + 1)
                result.extend(self._transform_inline_node(child, alt=alt))
                i += 1 + consumed
                continue

            # Regular node
            result.extend(self._transform_inline_node(child))
            i += 1

        return result

    def _transform_inline_node(self, node: SyntaxTreeNode, alt: str = "") -> list[InlineContent]:
        """Transform a single inline node to InlineContent.

        Args:
            node: The AST node to transform
            alt: Optional alt text extracted from {annotation} suffix
        """
        if node.type == "text":
            return [TextContent(content=node.content or "")]
        elif node.type == "strong":
            inner = []
            for child in node.children:
                inner.extend(self._transform_inline_node(child))
            return [StrongContent(content=inner)]
        elif node.type == "em":
            inner = []
            for child in node.children:
                inner.extend(self._transform_inline_node(child))
            return [EmphasisContent(content=inner)]
        elif node.type == "code_inline":
            return [CodeSpanContent(content=node.content or "")]
        elif node.type == "link":
            inner = []
            for child in node.children:
                inner.extend(self._transform_inline_node(child))
            return [
                LinkContent(
                    href=cast(str, node.attrs.get("href", "")),
                    title=cast(str | None, node.attrs.get("title")),
                    content=inner,
                )
            ]
        elif node.type == "image":
            # Alt text is in node.content (or children), not attrs['alt']
            md_alt = node.content or ""
            return [
                InlineImageContent(
                    src=cast(str, node.attrs.get("src", "")),
                    alt=md_alt,
                )
            ]
        elif node.type == "softbreak":
            return [TextContent(content=" ")]
        elif node.type == "hardbreak":
            return [TextContent(content="\n")]
        elif node.type == "math_inline":
            return [MathInlineContent(content=node.content or "", alt=alt)]
        else:
            # Unknown type, return as text if has content
            if node.content:
                return [TextContent(content=node.content)]
            return []

    def _extract_plain_text(self, inline: SyntaxTreeNode | None) -> str:
        """Extract plain text from inline content (for TTS).

        Uses <yap-alt> for math alt text. Skips <yap-cap> content (handled separately).
        """
        if not inline or not inline.children:
            return ""

        children = inline.children
        parts = []
        i = 0

        while i < len(children):
            child = children[i]

            # Skip yap-cap sections (handled by _create_image_block)
            if _is_html_tag(child, _YAP_CAP_OPEN):
                _, consumed = _extract_yap_cap(children, i)
                i += consumed if consumed else 1
                continue

            # Skip orphaned yap-alt (shouldn't appear outside math context)
            if _is_html_tag(child, _YAP_ALT_OPEN):
                _, consumed = _extract_yap_alt(children, i)
                i += consumed if consumed else 1
                continue

            # Skip closing tags
            if _is_html_tag(child, _YAP_CAP_CLOSE) or _is_html_tag(child, _YAP_ALT_CLOSE):
                i += 1
                continue

            # For math_inline, use <yap-alt> if present
            if child.type == "math_inline":
                alt, consumed = _extract_yap_alt(children, i + 1)
                if alt:
                    parts.append(alt)
                # else: no alt, skip the math for TTS
                i += 1 + consumed
                continue

            # Regular node
            parts.append(self._extract_plain_text_node(child))
            i += 1

        return "".join(parts)

    def _extract_plain_text_node(self, node: SyntaxTreeNode) -> str:
        """Extract plain text from a single inline node."""
        if node.type == "text":
            return node.content or ""
        elif node.type in ("strong", "em", "s", "link"):
            return "".join(self._extract_plain_text_node(c) for c in node.children)
        elif node.type == "code_inline":
            return node.content or ""
        elif node.type == "image":
            # Alt text is in node.content, not attrs['alt']
            return node.content or ""
        elif node.type in ("softbreak", "hardbreak"):
            return " "
        elif node.type == "math_inline":
            # Handled by _extract_plain_text with yap-alt lookup
            return ""
        elif node.type == "html_inline":
            # Skip HTML tags (yap annotations handled at higher level)
            return ""
        else:
            return node.content or ""


def transform_to_document(
    ast: SyntaxTreeNode,
    max_block_chars: int = 150,
    soft_limit_mult: float = 1.2,
    min_chunk_size: int = 30,
) -> StructuredDocument:
    """Transform markdown AST to StructuredDocument."""
    return DocumentTransformer(
        max_block_chars=max_block_chars,
        soft_limit_mult=soft_limit_mult,
        min_chunk_size=min_chunk_size,
    ).transform(ast)

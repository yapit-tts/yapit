"""Transform markdown AST to StructuredDocument.

Core concepts:
- yap-show: content goes to display only
- yap-speak: content goes to TTS only
- yap-cap: caption container for images (supports both)
- Math: display only (silent unless followed by yap-speak)

All audio content respects max_block_chars splitting.
Split content gets <span data-audio-idx="N"> wrappers in HTML.
"""

import re
from collections.abc import Sequence
from typing import Literal, cast
from urllib.parse import parse_qs, urlparse

from markdown_it.tree import SyntaxTreeNode

from yapit.gateway.markdown.models import (
    AudioChunk,
    BlockquoteBlock,
    CodeBlock,
    CodeSpanContent,
    ContentBlock,
    EmphasisContent,
    FootnoteItem,
    FootnoteRefContent,
    FootnotesBlock,
    HardbreakContent,
    HeadingBlock,
    ImageBlock,
    InlineContent,
    InlineImageContent,
    LinkContent,
    ListBlock,
    ListContent,
    ListItem,
    MathBlock,
    MathInlineContent,
    ParagraphBlock,
    ShowContent,
    SpeakContent,
    StrikethroughContent,
    StrongContent,
    StructuredDocument,
    TableBlock,
    TableCell,
    TextContent,
    ThematicBreak,
)
from yapit.gateway.markdown.parser import parse_markdown

# === TAG CONSTANTS ===

YAP_SHOW_OPEN = "<yap-show>"
YAP_SHOW_CLOSE = "</yap-show>"
YAP_SPEAK_OPEN = "<yap-speak>"
YAP_SPEAK_CLOSE = "</yap-speak>"
YAP_CAP_OPEN = "<yap-cap>"
YAP_CAP_CLOSE = "</yap-cap>"


def _is_tag(node: SyntaxTreeNode, tag: str) -> bool:
    """Check if node is an html_inline containing the specified tag."""
    return node.type == "html_inline" and node.content == tag


# === INLINE PROCESSING ===


class InlineProcessor:
    """Processes inline content to produce display HTML and TTS text.

    Handles yap-show (display only), yap-speak (TTS only), and math (display only).
    """

    def __init__(self) -> None:
        self.display_parts: list[str] = []
        self.tts_parts: list[str] = []
        self.in_show: int = 0  # Depth counter for nested show tags

    def process(self, nodes: list[SyntaxTreeNode]) -> tuple[str, str]:
        """Process nodes and return (display_html, tts_text)."""
        self.display_parts = []
        self.tts_parts = []
        self.in_show = 0
        self._process_nodes(nodes)
        return "".join(self.display_parts), "".join(self.tts_parts)

    def _process_nodes(self, nodes: list[SyntaxTreeNode]) -> None:
        """Walk through nodes, routing content appropriately."""
        i = 0
        while i < len(nodes):
            node = nodes[i]

            # Handle yap-show open
            if _is_tag(node, YAP_SHOW_OPEN):
                self.in_show += 1
                i += 1
                continue

            # Handle yap-show close
            if _is_tag(node, YAP_SHOW_CLOSE):
                self.in_show = max(0, self.in_show - 1)
                i += 1
                continue

            # Handle yap-speak: extract content, add to TTS only (unless in show zone)
            if _is_tag(node, YAP_SPEAK_OPEN):
                speak_content, consumed = self._extract_tag_content(nodes, i, YAP_SPEAK_OPEN, YAP_SPEAK_CLOSE)
                if speak_content and self.in_show == 0:
                    self.tts_parts.append(speak_content)
                i += consumed
                continue

            # Handle orphaned close tags gracefully
            if _is_tag(node, YAP_SPEAK_CLOSE) or _is_tag(node, YAP_CAP_CLOSE):
                i += 1
                continue

            # Handle yap-cap (shouldn't appear in regular inline, but skip if it does)
            if _is_tag(node, YAP_CAP_OPEN):
                _, consumed = self._extract_tag_content(nodes, i, YAP_CAP_OPEN, YAP_CAP_CLOSE)
                i += consumed
                continue

            # Regular node processing
            self._process_node(node)
            i += 1

    def _process_node(self, node: SyntaxTreeNode) -> None:
        """Process a single node, adding to display and/or TTS."""
        display_html = self._node_to_html(node)
        tts_text = self._node_to_tts(node)

        # Always add to display
        self.display_parts.append(display_html)

        # Only add to TTS if not in show zone
        if self.in_show == 0:
            self.tts_parts.append(tts_text)

    def _node_to_html(self, node: SyntaxTreeNode) -> str:
        """Convert node to HTML string."""
        if node.type == "text":
            return node.content or ""
        elif node.type == "strong":
            inner = "".join(self._node_to_html(c) for c in node.children)
            return f"<strong>{inner}</strong>"
        elif node.type == "em":
            inner = "".join(self._node_to_html(c) for c in node.children)
            return f"<em>{inner}</em>"
        elif node.type == "s":
            inner = "".join(self._node_to_html(c) for c in node.children)
            return f"<s>{inner}</s>"
        elif node.type == "code_inline":
            return f"<code>{node.content or ''}</code>"
        elif node.type == "link":
            href = node.attrs.get("href", "")
            title = node.attrs.get("title", "")
            inner = "".join(self._node_to_html(c) for c in node.children)
            title_attr = f' title="{title}"' if title else ""
            return f'<a href="{href}"{title_attr}>{inner}</a>'
        elif node.type == "image":
            src = node.attrs.get("src", "")
            alt = node.content or ""
            title = node.attrs.get("title", "")
            title_attr = f' title="{title}"' if title else ""
            return f'<img src="{src}" alt="{alt}"{title_attr} />'
        elif node.type == "softbreak":
            return " "
        elif node.type == "hardbreak":
            return "<br />"
        elif node.type == "math_inline":
            return f'<span class="math-inline">{node.content or ""}</span>'
        elif node.type == "html_inline":
            # Yap tags are handled by the caller (_process_nodes); any html_inline
            # reaching here is raw user HTML — drop it to prevent XSS.
            return ""
        elif node.type == "footnote_ref":
            # Footnote reference - render as superscript link
            label = node.meta.get("label", "") if node.meta else ""
            return f'<sup class="footnote-ref"><a href="#fn-{label}" id="fnref-{label}">[{label}]</a></sup>'
        elif node.type == "footnote_anchor":
            # Back-link anchor in footnote content - skip in HTML
            return ""
        else:
            return node.content or ""

    def _node_to_tts(self, node: SyntaxTreeNode) -> str:
        """Extract TTS text from node. Math and footnote refs are silent."""
        if node.type == "text":
            return node.content or ""
        elif node.type in ("strong", "em", "s", "link"):
            return "".join(self._node_to_tts(c) for c in node.children)
        elif node.type == "code_inline":
            return node.content or ""
        elif node.type == "image":
            return node.content or ""  # Alt text
        elif node.type in ("softbreak", "hardbreak"):
            return " "
        elif node.type == "math_inline":
            return ""  # Math is silent
        elif node.type == "html_inline":
            return ""  # Skip HTML tags
        elif node.type == "footnote_ref":
            return ""  # Footnote refs are silent
        elif node.type == "footnote_anchor":
            return ""  # Back-link anchors are silent
        else:
            return node.content or ""

    def _extract_tag_content(
        self, nodes: list[SyntaxTreeNode], start_idx: int, open_tag: str, close_tag: str
    ) -> tuple[str, int]:
        """Extract text content between open and close tags.

        Returns (content_text, nodes_consumed). If malformed, returns ("", 1).
        """
        if start_idx >= len(nodes) or not _is_tag(nodes[start_idx], open_tag):
            return "", 1

        parts: list[str] = []
        i = start_idx + 1
        while i < len(nodes):
            node = nodes[i]
            if _is_tag(node, close_tag):
                return "".join(parts), i - start_idx + 1
            # Extract plain text from content
            parts.append(self._node_to_tts(node))
            i += 1

        # Unclosed tag - treat as consumed but return nothing
        return "", i - start_idx


# === CAPTION PROCESSING ===


def process_caption(nodes: list[SyntaxTreeNode]) -> tuple[str, str]:
    """Process caption nodes to get (display_caption, tts_caption).

    Captions support full inline markdown including yap-show and yap-speak.
    """
    processor = InlineProcessor()
    return processor.process(nodes)


def extract_caption_nodes(children: list[SyntaxTreeNode], start_idx: int) -> tuple[list[SyntaxTreeNode], int]:
    """Extract nodes inside <yap-cap>...</yap-cap>.

    Returns (caption_nodes, nodes_consumed). If no caption, returns ([], 0).
    """
    if start_idx >= len(children):
        return [], 0

    if not _is_tag(children[start_idx], YAP_CAP_OPEN):
        return [], 0

    caption_nodes: list[SyntaxTreeNode] = []
    i = start_idx + 1
    while i < len(children):
        node = children[i]
        if _is_tag(node, YAP_CAP_CLOSE):
            return caption_nodes, i - start_idx + 1
        caption_nodes.append(node)
        i += 1

    # Unclosed - return nothing
    return [], 0


# === AST TRANSFORMATION ===


def transform_inline_to_ast(nodes: list[SyntaxTreeNode]) -> list[InlineContent]:
    """Transform inline nodes to our AST representation.

    - yap-show content becomes ShowContent (display-only, 0 TTS length)
    - yap-speak content becomes SpeakContent (TTS-only, has TTS length)
    - yap-cap is skipped (handled separately for images)
    """
    result: list[InlineContent] = []
    i = 0

    while i < len(nodes):
        node = nodes[i]

        # yap-show: collect inner nodes and create ShowContent (display-only, 0 TTS length)
        if _is_tag(node, YAP_SHOW_OPEN):
            depth = 1
            i += 1
            inner_nodes: list[SyntaxTreeNode] = []
            while i < len(nodes) and depth > 0:
                if _is_tag(nodes[i], YAP_SHOW_OPEN):
                    depth += 1
                elif _is_tag(nodes[i], YAP_SHOW_CLOSE):
                    depth -= 1
                if depth > 0:  # Don't include the close tag
                    inner_nodes.append(nodes[i])
                i += 1
            # Recursively transform inner content
            inner_ast = transform_inline_to_ast(inner_nodes)
            if inner_ast:
                result.append(ShowContent(content=inner_ast))
            continue

        # yap-speak: extract text content and add as SpeakContent
        # This has TTS length but renders as empty HTML
        if _is_tag(node, YAP_SPEAK_OPEN):
            depth = 1
            i += 1
            speak_text_parts: list[str] = []
            while i < len(nodes) and depth > 0:
                inner_node = nodes[i]
                if _is_tag(inner_node, YAP_SPEAK_OPEN):
                    depth += 1
                elif _is_tag(inner_node, YAP_SPEAK_CLOSE):
                    depth -= 1
                elif depth == 1 and inner_node.type == "text":
                    speak_text_parts.append(inner_node.content or "")
                i += 1
            speak_text = "".join(speak_text_parts)
            if speak_text:
                result.append(SpeakContent(content=speak_text))
            continue

        # Skip yap-cap content (handled separately for images)
        if _is_tag(node, YAP_CAP_OPEN):
            depth = 1
            i += 1
            while i < len(nodes) and depth > 0:
                if _is_tag(nodes[i], YAP_CAP_OPEN):
                    depth += 1
                elif _is_tag(nodes[i], YAP_CAP_CLOSE):
                    depth -= 1
                i += 1
            continue

        # Skip orphaned close tags
        if node.type == "html_inline" and node.content in (YAP_SHOW_CLOSE, YAP_SPEAK_CLOSE, YAP_CAP_CLOSE):
            i += 1
            continue

        # Transform regular nodes
        ast_node = _transform_inline_node(node)
        if ast_node:
            result.append(ast_node)
        i += 1

    return result


def _transform_inline_node(node: SyntaxTreeNode) -> InlineContent | None:
    """Transform a single inline node to InlineContent."""
    if node.type == "text":
        return TextContent(content=node.content or "")
    elif node.type == "strong":
        inner = []
        for child in node.children:
            ast = _transform_inline_node(child)
            if ast:
                inner.append(ast)
        return StrongContent(content=inner)
    elif node.type == "em":
        inner = []
        for child in node.children:
            ast = _transform_inline_node(child)
            if ast:
                inner.append(ast)
        return EmphasisContent(content=inner)
    elif node.type == "s":
        inner = []
        for child in node.children:
            ast = _transform_inline_node(child)
            if ast:
                inner.append(ast)
        return StrikethroughContent(content=inner)
    elif node.type == "code_inline":
        return CodeSpanContent(content=node.content or "")
    elif node.type == "link":
        inner = []
        for child in node.children:
            ast = _transform_inline_node(child)
            if ast:
                inner.append(ast)
        return LinkContent(
            href=cast(str, node.attrs.get("href", "")),
            title=cast(str | None, node.attrs.get("title")),
            content=inner,
        )
    elif node.type == "image":
        return InlineImageContent(
            src=cast(str, node.attrs.get("src", "")),
            alt=node.content or "",
        )
    elif node.type == "math_inline":
        return MathInlineContent(content=node.content or "")
    elif node.type == "softbreak":
        return TextContent(content=" ")
    elif node.type == "hardbreak":
        return HardbreakContent()
    elif node.type == "footnote_ref":
        label = node.meta.get("label", "") if node.meta else ""
        return FootnoteRefContent(label=label)
    elif node.type == "footnote_anchor":
        # Back-link anchors don't contribute to AST (they're navigational)
        return None
    return None


# === SPLITTING ===


class TextSplitter:
    """Splits text into chunks respecting max_block_chars.

    Splitting strategy (in order of preference):
    1. Sentence boundaries (.!?)
    2. Clause separators (,—:;) - when sentences are too long
    3. Word boundaries - last resort for very long clauses
    """

    # Sentence-ending punctuation
    SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

    # Pause pattern: clause separators optionally followed by closing quotes/parens
    # This ensures we don't orphan closing punctuation at the start of the next chunk
    # Includes straight quotes, curly quotes (U+201C/D, U+2018/9), parens, brackets
    PAUSE_PATTERN = re.compile(r"[,—:;][\"')\]\u201c\u201d\u2018\u2019]?")

    def __init__(
        self,
        max_chars: int,
        soft_limit_mult: float = 1.3,
        min_chunk_size: int = 40,
    ):
        self.max_chars = max_chars
        self.soft_max = int(max_chars * soft_limit_mult)
        self.min_chunk_size = min_chunk_size

    def get_chunk_ranges(self, text: str) -> list[tuple[int, int]]:
        """Get (start, end) character ranges for each chunk."""
        if not text or len(text) <= self.max_chars:
            return [(0, len(text))] if text else []

        sentences = self.SENTENCE_END.split(text)

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
            if len(sentence) > self.soft_max:
                # Flush current chunk if any
                if current_end > current_start:
                    ranges.append((current_start, current_end))
                # Split the long sentence at natural pause points
                self._split_long_sentence(sentence, sent_start, ranges)
                current_start = sent_end
                current_end = sent_end
                continue

            # Check if adding this sentence would exceed limit
            potential_len = sent_end - current_start
            if potential_len <= self.max_chars:
                current_end = sent_end
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

    def _split_long_sentence(self, sentence: str, sent_start: int, ranges: list[tuple[int, int]]) -> None:
        """Split a long sentence at natural pause points, falling back to word boundaries."""
        # Find all pause points (comma, m-dash, colon, semicolon)
        pause_matches = list(self.PAUSE_PATTERN.finditer(sentence))
        # Positions after the pause character (where next clause starts)
        pause_positions = [m.end() for m in pause_matches]

        chunk_pos = 0
        while chunk_pos < len(sentence):
            remaining = len(sentence) - chunk_pos
            if remaining <= self.max_chars:
                # Remaining text fits in one chunk
                ranges.append((sent_start + chunk_pos, sent_start + len(sentence)))
                break

            # Look for a natural pause point
            split_pos = self._find_pause_split(sentence, chunk_pos, pause_positions)

            if split_pos is not None:
                # Split at the pause point (include the pause char, trim trailing space)
                ranges.append((sent_start + chunk_pos, sent_start + split_pos))
                # Skip whitespace after the pause
                chunk_pos = split_pos
                while chunk_pos < len(sentence) and sentence[chunk_pos] == " ":
                    chunk_pos += 1
            else:
                # Fall back to word boundary split
                target_end = min(chunk_pos + self.max_chars, len(sentence))
                if target_end < len(sentence):
                    boundary = sentence.rfind(" ", chunk_pos, target_end)
                    if boundary > chunk_pos:
                        # Check if this would leave a tiny orphan
                        orphan_len = len(sentence) - (boundary + 1)
                        if orphan_len < self.min_chunk_size:
                            # Include the orphan rather than creating a bad split
                            target_end = len(sentence)
                        else:
                            target_end = boundary + 1
                ranges.append((sent_start + chunk_pos, sent_start + target_end))
                chunk_pos = target_end

    def _find_pause_split(self, sentence: str, chunk_pos: int, pause_positions: list[int]) -> int | None:
        """Find the best pause point to split at, or None if none suitable.

        Prefers pause points that:
        1. Are within max_chars from chunk_pos
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
            if chunk_len > self.max_chars:
                continue

            # Skip if this would leave a tiny orphan (unless it's the only option)
            if next_chunk_len < self.min_chunk_size and next_chunk_len > 0:
                # Only consider this if we have no better option
                if best_pos is None:
                    best_pos = pos
                continue

            # This is a valid split point - prefer later ones
            best_pos = pos

        return best_pos


def split_with_spans(
    text: str,
    html: str,
    ast: list[InlineContent],
    splitter: TextSplitter,
    start_idx: int,
) -> tuple[str, list[AudioChunk]]:
    """Split text and wrap HTML in span tags, preserving formatting.

    Returns (html_with_spans, audio_chunks).
    If text doesn't need splitting, returns original HTML (no spans).
    """
    text = text.strip()
    if not text:
        return html, []

    chunk_ranges = splitter.get_chunk_ranges(text)

    if len(chunk_ranges) <= 1:
        # No splitting needed
        return html, [AudioChunk(text=text, audio_block_idx=start_idx, ast=ast)]

    # AST may have trailing 0-length nodes (math, footnote refs) past the stripped text length.
    # Extend last chunk's end to include them.
    ast_len = sum(get_inline_length(n) for n in ast)

    # Slice AST for each chunk and render to HTML with span wrappers
    audio_chunks: list[AudioChunk] = []
    html_parts: list[str] = []

    for i, (chunk_start, chunk_end) in enumerate(chunk_ranges):
        chunk_text = text[chunk_start:chunk_end].strip()
        idx = start_idx + i

        # For the last chunk, extend end to include trailing 0-length display elements
        is_last = i == len(chunk_ranges) - 1
        ast_end = max(chunk_end, ast_len) if is_last else chunk_end

        # Slice AST and render to HTML
        sliced_ast = slice_ast(ast, chunk_start, ast_end)
        chunk_html = render_ast_to_html(sliced_ast)

        html_parts.append(f'<span data-audio-idx="{idx}">{chunk_html}</span>')
        audio_chunks.append(AudioChunk(text=chunk_text, audio_block_idx=idx, ast=sliced_ast))

    return " ".join(html_parts), audio_chunks


# === AST SLICING ===


def slice_ast(ast: list[InlineContent], start: int, end: int) -> list[InlineContent]:
    """Slice AST to extract content between character positions.

    Handles nested formatting - if a split falls inside a bold/italic span,
    the span is properly closed in the first chunk and reopened in the second.

    0-length nodes (math, footnote refs) need special handling at boundaries:
    they should be included when at the start or end of a range, not skipped.
    """
    result: list[InlineContent] = []
    pos = 0

    for node in ast:
        node_len = get_inline_length(node)
        node_end = pos + node_len

        # Skip nodes entirely before our range
        # For 0-length nodes at pos==start: don't skip (they're AT the boundary, not before)
        if node_end < start or (node_end == start and node_len > 0):
            pos = node_end
            continue

        # Stop if we're past our range (use > not >= to include 0-length nodes at boundary)
        if pos > end:
            break

        # Calculate overlap
        overlap_start = max(0, start - pos)
        overlap_end = min(node_len, end - pos)

        # Slice the node
        sliced = slice_inline_node(node, overlap_start, overlap_end)
        if sliced:
            result.extend(sliced)

        pos = node_end

    return result


def slice_inline_node(node: InlineContent, start: int, end: int) -> list[InlineContent]:
    """Slice a single inline node at given character positions."""
    match node:
        case TextContent():
            content = node.content[start:end]
            return [TextContent(content=content)] if content else []
        case CodeSpanContent():
            content = node.content[start:end]
            return [CodeSpanContent(content=content)] if content else []
        case StrongContent():
            inner = slice_ast(node.content, start, end)
            return [StrongContent(content=inner)] if inner else []
        case EmphasisContent():
            inner = slice_ast(node.content, start, end)
            return [EmphasisContent(content=inner)] if inner else []
        case StrikethroughContent():
            inner = slice_ast(node.content, start, end)
            return [StrikethroughContent(content=inner)] if inner else []
        case LinkContent():
            inner = slice_ast(node.content, start, end)
            return [LinkContent(href=node.href, title=node.title, content=inner)] if inner else []
        case InlineImageContent():
            # Images are atomic - include whole thing if start of slice
            return [node] if start == 0 else []
        case MathInlineContent():
            # Math has 0 TTS length but should be displayed.
            # Include it if the slice starts at position 0 (i.e., we're at
            # the position where this math appears in the TTS stream)
            return [node] if start == 0 else []
        case SpeakContent():
            # Speak content is sliced like text (contributes to TTS length)
            content = node.content[start:end]
            return [SpeakContent(content=content)] if content else []
        case HardbreakContent():
            # TTS length 1 — include if slice covers it
            return [node] if start == 0 and end >= 1 else []
        case FootnoteRefContent():
            # Footnote refs have 0 TTS length, include at slice start
            return [node] if start == 0 else []
        case ShowContent():
            # ShowContent has 0 TTS length (display-only), include at slice start
            return [node] if start == 0 else []
        case ListContent():
            # Atomic — include whole list at slice start, don't split across chunks.
            # Splitting a list produces multiple <ul>s with separate bullets,
            # which visually breaks the structure.
            return [node] if start == 0 and end > 0 else []
    return []


def get_inline_length(node: InlineContent) -> int:
    """Get the TTS text length of an inline node."""
    match node:
        case TextContent() | CodeSpanContent():
            return len(node.content)
        case StrongContent() | EmphasisContent() | StrikethroughContent() | LinkContent():
            return sum(get_inline_length(child) for child in node.content)
        case InlineImageContent():
            return len(node.alt)
        case MathInlineContent():
            # Math is silent in TTS, so it contributes 0 to TTS length
            return 0
        case SpeakContent():
            # Speak content contributes its full length to TTS
            return len(node.content)
        case HardbreakContent():
            return 1  # Maps to " " in TTS
        case FootnoteRefContent():
            # Footnote refs are silent (display-only)
            return 0
        case ShowContent():
            # ShowContent is display-only, no TTS contribution
            return 0
        case ListContent():
            # Items are joined with " " in TTS text, so add (N-1) join spaces
            item_lengths = [sum(get_inline_length(child) for child in item) for item in node.items]
            return sum(item_lengths) + max(0, len(node.items) - 1)
    return 0


def render_ast_to_html(ast: list[InlineContent]) -> str:
    """Render our InlineContent AST back to HTML."""
    return "".join(render_inline_content_html(node) for node in ast)


def render_inline_content_html(node: InlineContent) -> str:
    """Render a single InlineContent node to HTML."""
    match node:
        case TextContent():
            return node.content
        case CodeSpanContent():
            return f"<code>{node.content}</code>"
        case StrongContent():
            return f"<strong>{render_ast_to_html(node.content)}</strong>"
        case EmphasisContent():
            return f"<em>{render_ast_to_html(node.content)}</em>"
        case StrikethroughContent():
            return f"<s>{render_ast_to_html(node.content)}</s>"
        case LinkContent():
            inner = render_ast_to_html(node.content)
            title_attr = f' title="{node.title}"' if node.title else ""
            return f'<a href="{node.href}"{title_attr}>{inner}</a>'
        case InlineImageContent():
            return f'<img src="{node.src}" alt="{node.alt}" />'
        case MathInlineContent():
            return f'<span class="math-inline">{node.content}</span>'
        case SpeakContent():
            # Speak content is TTS-only, doesn't render to display HTML
            return ""
        case HardbreakContent():
            return "<br />"
        case FootnoteRefContent():
            # Render as superscript link to footnote, with id for back-navigation
            if node.has_content:
                return f'<sup class="footnote-ref"><a href="#fn-{node.label}" id="fnref-{node.label}">[{node.label}]</a></sup>'
            else:
                # No matching footnote - render as plain text (no link)
                return f'<sup class="footnote-ref-orphan">[{node.label}]</sup>'
        case ShowContent():
            # ShowContent renders its inner content (display-only)
            return render_ast_to_html(node.content)
        case ListContent():
            tag = "ol" if node.ordered else "ul"
            start_attr = f' start="{node.start}"' if node.ordered and node.start else ""
            items_html = "".join(f"<li>{render_ast_to_html(item)}</li>" for item in node.items)
            return f"<{tag}{start_attr}>{items_html}</{tag}>"
    return ""


# === DOCUMENT TRANSFORMER ===


class DocumentTransformer:
    """Transforms markdown AST to StructuredDocument."""

    def __init__(
        self,
        max_block_chars: int = 150,
        soft_limit_mult: float = 1.2,
        min_chunk_size: int = 30,
    ):
        self.splitter = TextSplitter(max_block_chars, soft_limit_mult, min_chunk_size)
        self._block_counter = 0
        self._audio_idx_counter = 0
        self._skip_indices: set[int] = set()

    def _next_block_id(self) -> str:
        id_ = f"b{self._block_counter}"
        self._block_counter += 1
        return id_

    def _next_audio_idx(self) -> int:
        idx = self._audio_idx_counter
        self._audio_idx_counter += 1
        return idx

    def transform(self, ast: SyntaxTreeNode) -> StructuredDocument:
        """Transform AST root to StructuredDocument."""
        self._block_counter = 0
        self._audio_idx_counter = 0
        self._skip_indices = set()

        # Pre-process: find display math followed by yap-speak paragraphs
        self._find_math_annotations(ast)

        blocks = self._transform_children(ast)
        doc = StructuredDocument(blocks=blocks)

        # Post-process: deduplicate footnote labels and match refs with content
        self._process_footnotes(doc)

        return doc

    def _process_footnotes(self, doc: StructuredDocument) -> None:
        """Post-process footnotes: deduplicate labels and match refs with content.

        - If multiple footnotes have the same label, rename them: "1" -> "1", "1" -> "1-2", etc.
        - Mark inline refs that have no matching footnote content (has_content=False)
        - Mark footnote content that has no matching inline ref (has_ref=False)
        - Update HTML to use deduplicated labels
        """
        # Collect all footnote refs and content
        refs: list[tuple[FootnoteRefContent, str]] = []  # (ref, original_label)
        footnote_items: list[FootnoteItem] = []

        def collect_refs_from_block(block: ContentBlock) -> None:
            """Recursively collect footnote refs from block AST."""
            if isinstance(block, (ParagraphBlock, HeadingBlock)):
                collect_refs_from_ast(block.ast)
            elif isinstance(block, ListBlock):
                for item in block.items:
                    collect_refs_from_ast(item.ast)
            elif isinstance(block, BlockquoteBlock):
                for nested in block.blocks:
                    collect_refs_from_block(nested)
            elif isinstance(block, FootnotesBlock):
                footnote_items.extend(block.items)

        def collect_refs_from_ast(ast: list[InlineContent]) -> None:
            """Recursively collect footnote refs from inline AST."""
            for node in ast:
                if isinstance(node, FootnoteRefContent):
                    refs.append((node, node.label))
                elif isinstance(node, (StrongContent, EmphasisContent, LinkContent, ShowContent)):
                    collect_refs_from_ast(node.content)

        for block in doc.blocks:
            collect_refs_from_block(block)

        if not refs and not footnote_items:
            return

        # Deduplicate footnote content labels
        label_counts: dict[str, int] = {}
        label_map: dict[str, str] = {}  # original_label -> deduplicated_label

        for item in footnote_items:
            original_label = item.label
            count = label_counts.get(original_label, 0)
            label_counts[original_label] = count + 1

            if count == 0:
                # First occurrence, keep original
                label_map[f"{original_label}:{count}"] = original_label
            else:
                # Subsequent occurrences, add suffix
                new_label = f"{original_label}-{count + 1}"
                label_map[f"{original_label}:{count}"] = new_label
                item.label = new_label

        # Build set of content labels for matching
        content_labels = {item.label for item in footnote_items}

        # Deduplicate refs and match with content
        ref_label_counts: dict[str, int] = {}
        for ref, original_label in refs:
            count = ref_label_counts.get(original_label, 0)
            ref_label_counts[original_label] = count + 1

            # Get the deduplicated label for this occurrence
            deduped_label = label_map.get(f"{original_label}:{count}", original_label)
            ref.label = deduped_label

            # Check if matching content exists
            ref.has_content = deduped_label in content_labels

        # Mark footnotes without matching refs
        ref_labels = {ref.label for ref, _ in refs}
        for item in footnote_items:
            item.has_ref = item.label in ref_labels

    def _find_math_annotations(self, ast: SyntaxTreeNode) -> None:
        """Find display math blocks followed by yap-speak annotation paragraphs.

        Marks those paragraphs for skipping.
        """
        children = ast.children
        for i, child in enumerate(children):
            if child.type == "math_block" and i + 1 < len(children):
                next_child = children[i + 1]
                if self._is_speak_only_paragraph(next_child):
                    self._skip_indices.add(i + 1)

    def _is_speak_only_paragraph(self, node: SyntaxTreeNode) -> bool:
        """Check if paragraph contains only <yap-speak>...</yap-speak>."""
        if node.type != "paragraph" or not node.children:
            return False
        inline = node.children[0]
        if inline.type != "inline" or not inline.children:
            return False

        children = inline.children
        # Must be: <yap-speak>...</yap-speak> only
        if len(children) < 2:
            return False
        if not _is_tag(children[0], YAP_SPEAK_OPEN):
            return False

        # Find closing tag
        for i, child in enumerate(children[1:], 1):
            if _is_tag(child, YAP_SPEAK_CLOSE):
                # Check nothing meaningful after
                remaining = children[i + 1 :]
                return all(c.type == "text" and not (c.content or "").strip() for c in remaining)
        return False

    def _extract_speak_from_paragraph(self, node: SyntaxTreeNode) -> str:
        """Extract yap-speak content from a speak-only paragraph."""
        if not node.children:
            return ""
        inline = node.children[0]
        if not inline.children:
            return ""

        children = inline.children
        parts: list[str] = []
        in_speak = False

        for child in children:
            if _is_tag(child, YAP_SPEAK_OPEN):
                in_speak = True
            elif _is_tag(child, YAP_SPEAK_CLOSE):
                in_speak = False
            elif in_speak and child.type == "text":
                parts.append(child.content or "")

        return "".join(parts)

    def _transform_children(self, node: SyntaxTreeNode) -> list[ContentBlock]:
        """Transform all children of a node."""
        blocks: list[ContentBlock] = []
        yap_show_acc: list[ContentBlock] | None = None
        saved_audio_idx = 0

        for i, child in enumerate(node.children):
            if i in self._skip_indices:
                continue

            if child.type == "html_block":
                content = (child.content or "").strip()

                if yap_show_acc is None:
                    # Check for yap-show opening without close in same block
                    if content.startswith(YAP_SHOW_OPEN) and YAP_SHOW_CLOSE not in content:
                        yap_show_acc = []
                        saved_audio_idx = self._audio_idx_counter
                        # Re-parse any content after the opening tag
                        inner = content[len(YAP_SHOW_OPEN) :].strip()
                        if inner:
                            inner_tree = parse_markdown(inner)
                            for c in inner_tree.children:
                                yap_show_acc.extend(self._transform_node(c, inner_tree))
                        continue
                    # Self-contained or other html_block — normal dispatch
                    blocks.extend(self._transform_node(child, parent=node, index=i))
                    continue

                # In accumulation mode — check for close tag
                if YAP_SHOW_CLOSE in content:
                    before_close = content.split(YAP_SHOW_CLOSE)[0].strip()
                    if before_close:
                        inner_tree = parse_markdown(before_close)
                        for c in inner_tree.children:
                            yap_show_acc.extend(self._transform_node(c, inner_tree))
                    _strip_audio_recursive(yap_show_acc)
                    self._audio_idx_counter = saved_audio_idx
                    blocks.extend(yap_show_acc)
                    yap_show_acc = None
                    continue
                # html_block inside yap-show without close tag — re-parse its content
                inner_tree = parse_markdown(content)
                for c in inner_tree.children:
                    yap_show_acc.extend(self._transform_node(c, inner_tree))
                continue

            if yap_show_acc is not None:
                # Non-html_block inside yap-show — transform normally, accumulate
                yap_show_acc.extend(self._transform_node(child, parent=node, index=i))
                continue

            blocks.extend(self._transform_node(child, parent=node, index=i))

        # Unclosed yap-show at end of document — include content anyway
        if yap_show_acc:
            _strip_audio_recursive(yap_show_acc)
            self._audio_idx_counter = saved_audio_idx
            blocks.extend(yap_show_acc)

        return blocks

    def _transform_node(
        self,
        node: SyntaxTreeNode,
        parent: SyntaxTreeNode | None = None,
        index: int = 0,
    ) -> Sequence[ContentBlock]:
        """Transform a single AST node to ContentBlock(s)."""
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
            "math_block": lambda n: self._transform_math(n, parent, index),
            "footnote_block": self._transform_footnote_block,
            "html_block": self._transform_html_block,
        }

        handler = handlers.get(node.type)
        if handler:
            return handler(node)
        return []

    def _transform_heading(self, node: SyntaxTreeNode) -> list[ContentBlock]:
        """Transform heading node."""
        level = cast(Literal[1, 2, 3, 4, 5, 6], int(node.tag[1]))
        inline = node.children[0] if node.children else None
        children = inline.children if inline else []

        processor = InlineProcessor()
        html, tts_text = processor.process(children)
        ast = transform_inline_to_ast(children)

        audio_chunks: list[AudioChunk] = []
        if tts_text.strip():
            html, audio_chunks = split_with_spans(tts_text, html, ast, self.splitter, self._audio_idx_counter)
            self._audio_idx_counter += len(audio_chunks)

        return [
            HeadingBlock(
                id=self._next_block_id(),
                level=level,
                html=html,
                ast=ast,
                audio_chunks=audio_chunks,
            )
        ]

    def _transform_paragraph(self, node: SyntaxTreeNode) -> Sequence[ContentBlock]:
        """Transform paragraph node."""
        inline = node.children[0] if node.children else None
        children = inline.children if inline else []

        # Check for standalone image
        if self._is_standalone_image(children):
            return [self._create_image_block(children)]

        processor = InlineProcessor()
        html, tts_text = processor.process(children)
        ast = transform_inline_to_ast(children)

        audio_chunks: list[AudioChunk] = []
        if tts_text.strip():
            html, audio_chunks = split_with_spans(tts_text, html, ast, self.splitter, self._audio_idx_counter)
            self._audio_idx_counter += len(audio_chunks)

        return [
            ParagraphBlock(
                id=self._next_block_id(),
                html=html,
                ast=ast,
                audio_chunks=audio_chunks,
            )
        ]

    def _is_standalone_image(self, children: list[SyntaxTreeNode]) -> bool:
        """Check if children represent a standalone image (with optional caption)."""
        yap_depth = 0
        meaningful = []

        for child in children:
            if child.type == "html_inline":
                content = child.content or ""
                if content in (YAP_CAP_OPEN, YAP_SHOW_OPEN, YAP_SPEAK_OPEN):
                    yap_depth += 1
                    continue
                elif content in (YAP_CAP_CLOSE, YAP_SHOW_CLOSE, YAP_SPEAK_CLOSE):
                    yap_depth = max(0, yap_depth - 1)
                    continue

            if yap_depth > 0:
                continue

            if child.type in ("softbreak", "hardbreak"):
                continue
            if child.type == "text" and not (child.content or "").strip():
                continue

            meaningful.append(child)

        return len(meaningful) == 1 and meaningful[0].type == "image"

    def _create_image_block(self, children: list[SyntaxTreeNode]) -> ImageBlock:
        """Create ImageBlock from image paragraph children."""
        # Find the image
        img_idx = next(i for i, c in enumerate(children) if c.type == "image")
        img_node = children[img_idx]

        src = img_node.attrs.get("src", "")
        alt = img_node.content or ""
        title = img_node.attrs.get("title")

        # Parse layout from URL
        width_pct, row_group = self._parse_image_metadata(src)
        clean_src = src.split("?")[0] if "?" in src else src

        # Extract caption
        caption_nodes, _ = extract_caption_nodes(children, img_idx + 1)
        caption = ""
        caption_html = ""
        caption_ast: list[InlineContent] = []
        tts_text = ""

        if caption_nodes:
            caption, tts_text = process_caption(caption_nodes)
            caption_html = caption  # Will be updated if splitting needed
            caption_ast = transform_inline_to_ast(caption_nodes)
        else:
            tts_text = alt  # Fall back to alt text
            # For plain alt text, create simple text AST
            caption_ast = [TextContent(content=alt)] if alt else []

        # Create audio chunks
        audio_chunks: list[AudioChunk] = []
        if tts_text.strip():
            caption_html, audio_chunks = split_with_spans(
                tts_text, caption_html or tts_text, caption_ast, self.splitter, self._audio_idx_counter
            )
            self._audio_idx_counter += len(audio_chunks)

        return ImageBlock(
            id=self._next_block_id(),
            src=clean_src,
            alt=alt,
            caption=caption if caption else None,
            caption_html=caption_html if caption_nodes and len(audio_chunks) > 1 else None,
            title=title,
            width_pct=width_pct,
            row_group=row_group,
            audio_chunks=audio_chunks,
        )

    def _parse_image_metadata(self, src: str) -> tuple[float | None, str | None]:
        """Parse width_pct and row_group from URL query params."""
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

    def _transform_list(self, node: SyntaxTreeNode) -> list[ContentBlock]:
        """Transform list node."""
        ordered = node.type == "ordered_list"
        start = cast(int | None, node.attrs.get("start")) if ordered else None

        items: list[ListItem] = []

        for list_item in node.children:
            # Collect segments in document order: (is_list, html, tts, ast)
            segments: list[tuple[bool, str, str, list[InlineContent]]] = []
            item_ast: list[InlineContent] = []
            has_nested = False

            for child in list_item.children:
                if child.type == "paragraph":
                    inline = child.children[0] if child.children else None
                    children = inline.children if inline else []

                    processor = InlineProcessor()
                    html, tts = processor.process(children)
                    segments.append((False, html, tts, transform_inline_to_ast(children)))
                    item_ast.extend(transform_inline_to_ast(children))

                elif child.type in ("bullet_list", "ordered_list"):
                    has_nested = True
                    nested_html, nested_tts = self._render_nested_list(child)
                    nested_ast_node = self._build_nested_list_ast(child)
                    segments.append((True, nested_html, nested_tts, [nested_ast_node]))
                    if item_ast:
                        item_ast.append(TextContent(content=" "))
                    item_ast.append(nested_ast_node)

            full_html = " ".join(seg_html for _, seg_html, _, _ in segments)

            if not has_nested:
                # No nested lists: combine and split as one (existing behavior)
                full_tts = " ".join(seg_tts for _, _, seg_tts, _ in segments)
                audio_chunks: list[AudioChunk] = []
                if full_tts.strip():
                    full_html, audio_chunks = split_with_spans(
                        full_tts, full_html, item_ast, self.splitter, self._audio_idx_counter
                    )
                    self._audio_idx_counter += len(audio_chunks)
            else:
                # Has nested lists: split each segment independently so chunk
                # boundaries align with the paragraph→nested-list visual boundary.
                # Prevents the "highlight 1 behind" bug where a chunk straddles both.
                audio_chunks = []
                for _, seg_html, seg_tts, seg_ast in segments:
                    if seg_tts.strip():
                        _, seg_chunks = split_with_spans(
                            seg_tts, seg_html, seg_ast, self.splitter, self._audio_idx_counter
                        )
                        self._audio_idx_counter += len(seg_chunks)
                        audio_chunks.extend(seg_chunks)

            items.append(
                ListItem(
                    html=full_html,
                    ast=item_ast,
                    audio_chunks=audio_chunks,
                )
            )

        return [
            ListBlock(
                id=self._next_block_id(),
                ordered=ordered,
                start=start,
                items=items,
            )
        ]

    def _render_nested_list(self, node: SyntaxTreeNode) -> tuple[str, str]:
        """Render nested list to HTML and TTS text."""
        ordered = node.type == "ordered_list"
        tag = "ol" if ordered else "ul"
        start_attr = f' start="{node.attrs.get("start")}"' if ordered and node.attrs.get("start") else ""

        html_parts: list[str] = []
        tts_parts: list[str] = []

        for list_item in node.children:
            item_html: list[str] = []
            item_tts: list[str] = []

            for child in list_item.children:
                if child.type == "paragraph":
                    inline = child.children[0] if child.children else None
                    children = inline.children if inline else []
                    processor = InlineProcessor()
                    html, tts = processor.process(children)
                    item_html.append(html)
                    item_tts.append(tts)
                elif child.type in ("bullet_list", "ordered_list"):
                    nested_html, nested_tts = self._render_nested_list(child)
                    item_html.append(nested_html)
                    item_tts.append(nested_tts)

            html_parts.append(f"<li>{' '.join(item_html)}</li>")
            tts_parts.append(" ".join(item_tts))

        html = f"<{tag}{start_attr}>{''.join(html_parts)}</{tag}>"
        tts = " ".join(tts_parts)
        return html, tts

    def _build_nested_list_ast(self, node: SyntaxTreeNode) -> ListContent:
        """Build a ListContent AST node from a nested list syntax tree node.

        Mirrors _render_nested_list but produces AST instead of HTML.
        Join spaces between parts within an item are explicit TextContent(" ")
        nodes so that get_inline_length stays in sync with the TTS text.
        """
        ordered = node.type == "ordered_list"
        start = cast(int | None, node.attrs.get("start")) if ordered else None

        items: list[list[InlineContent]] = []
        for list_item in node.children:
            item_ast: list[InlineContent] = []
            for child in list_item.children:
                if child.type == "paragraph":
                    inline = child.children[0] if child.children else None
                    children = inline.children if inline else []
                    if item_ast:
                        item_ast.append(TextContent(content=" "))
                    item_ast.extend(transform_inline_to_ast(children))
                elif child.type in ("bullet_list", "ordered_list"):
                    if item_ast:
                        item_ast.append(TextContent(content=" "))
                    item_ast.append(self._build_nested_list_ast(child))
            items.append(item_ast)

        return ListContent(ordered=ordered, start=start, items=items)

    def _transform_blockquote(self, node: SyntaxTreeNode) -> list[BlockquoteBlock]:
        r"""Transform blockquote node.

        Detects callout syntax: > [!COLOR] Optional Title
        Valid colors: BLUE, GREEN, PURPLE, RED, YELLOW, TEAL

        In markdown, blockquote lines merge into paragraphs with softbreaks:
        "> [!BLUE] Title\n> Content" becomes one paragraph with:
        - text "[!BLUE] Title"
        - softbreak
        - text "Content"

        We extract callout info from the first line, then transform content after softbreak.
        """
        result = self._extract_callout_info(node)
        if result is None:
            # Regular blockquote
            inner_blocks = self._transform_children(node)
            return [
                BlockquoteBlock(
                    id=self._next_block_id(),
                    blocks=inner_blocks,
                )
            ]

        callout_type, callout_title, first_para_content_nodes, remaining_children = result

        # Generate audio for callout title FIRST (before nested content)
        # so audio indices are in visual order: title, then content
        title_audio: list[AudioChunk] = []
        if callout_title:
            title_audio = [
                AudioChunk(
                    text=callout_title,
                    audio_block_idx=self._next_audio_idx(),
                    ast=[TextContent(content=callout_title)],
                )
            ]

        # Build content blocks
        blocks: list[ContentBlock] = []

        # If there's content after the callout marker line in first paragraph, transform it
        if first_para_content_nodes:
            processor = InlineProcessor()
            html, tts_text = processor.process(first_para_content_nodes)
            ast = transform_inline_to_ast(first_para_content_nodes)

            audio_chunks: list[AudioChunk] = []
            if tts_text.strip():
                html, audio_chunks = split_with_spans(tts_text, html, ast, self.splitter, self._audio_idx_counter)
                self._audio_idx_counter += len(audio_chunks)

            blocks.append(
                ParagraphBlock(
                    id=self._next_block_id(),
                    html=html,
                    ast=ast,
                    audio_chunks=audio_chunks,
                )
            )

        # Transform remaining blockquote children
        for child in remaining_children:
            blocks.extend(self._transform_node(child))

        return [
            BlockquoteBlock(
                id=self._next_block_id(),
                callout_type=callout_type,
                callout_title=callout_title,
                blocks=blocks,
                audio_chunks=title_audio,
            )
        ]

    def _extract_callout_info(
        self, node: SyntaxTreeNode
    ) -> tuple[str, str | None, list[SyntaxTreeNode], list[SyntaxTreeNode]] | None:
        """Extract callout type and title from blockquote.

        Returns None if not a callout.
        Otherwise returns (callout_type, callout_title, first_para_content_nodes, remaining_children):
        - callout_type: "BLUE", "GREEN", etc.
        - callout_title: Optional title text after [!COLOR]
        - first_para_content_nodes: AST nodes after softbreak in first paragraph (may be empty)
        - remaining_children: Blockquote children after the first paragraph
        """
        if not node.children:
            return None

        first_child = node.children[0]
        if first_child.type != "paragraph":
            return None

        # Get inline content
        inline = first_child.children[0] if first_child.children else None
        if not inline or inline.type != "inline" or not inline.children:
            return None

        # Check first text node for callout pattern
        first_node = inline.children[0]
        if first_node.type != "text":
            return None

        text = first_node.content or ""
        match = re.match(r"^\[!(\w+)\]\s*(.*)", text)
        if not match:
            return None

        callout_type = match.group(1).upper()
        if callout_type == "GREY":
            callout_type = "GRAY"
        valid_colors = {"BLUE", "GREEN", "PURPLE", "RED", "YELLOW", "TEAL", "GRAY"}
        if callout_type not in valid_colors:
            return None

        # Find softbreak to separate title from content
        # Everything before softbreak = title line
        # Everything after softbreak = first paragraph content
        title_parts = [match.group(2)] if match.group(2) else []
        softbreak_idx = None

        for i, child in enumerate(inline.children[1:], start=1):
            if child.type in ("softbreak", "hardbreak"):
                softbreak_idx = i
                break
            # Collect title text (before softbreak)
            title_parts.append(self._extract_plain_text(child))

        title = " ".join(title_parts).strip() or None

        # Content after softbreak in first paragraph
        first_para_content_nodes: list[SyntaxTreeNode] = []
        if softbreak_idx is not None:
            first_para_content_nodes = list(inline.children[softbreak_idx + 1 :])

        # Remaining blockquote children (after first paragraph)
        remaining_children = list(node.children[1:])

        return callout_type, title, first_para_content_nodes, remaining_children

    def _extract_plain_text(self, node: SyntaxTreeNode) -> str:
        """Extract plain text from a node, recursively."""
        if node.type == "text":
            return node.content or ""
        elif node.type == "code_inline":
            return node.content or ""
        elif node.children:
            return "".join(self._extract_plain_text(c) for c in node.children)
        return ""

    def _transform_footnote_block(self, node: SyntaxTreeNode) -> list[FootnotesBlock]:
        """Transform footnote_block container into FootnotesBlock.

        The footnote_block contains multiple footnote children, each with its content.
        """
        items: list[FootnoteItem] = []

        for footnote_node in node.children:
            if footnote_node.type != "footnote":
                continue

            label = footnote_node.meta.get("label", "") if footnote_node.meta else ""

            # Transform footnote content (paragraphs, etc.)
            # Skip footnote_anchor nodes (back-links)
            content_blocks: list[ContentBlock] = []
            for child in footnote_node.children:
                if child.type == "footnote_anchor":
                    continue
                content_blocks.extend(self._transform_node(child))

            items.append(
                FootnoteItem(
                    label=label,
                    blocks=content_blocks,
                )
            )

        if not items:
            return []

        return [
            FootnotesBlock(
                id=self._next_block_id(),
                items=items,
            )
        ]

    def _transform_code(self, node: SyntaxTreeNode) -> list[CodeBlock]:
        """Transform code block."""
        language = node.info if hasattr(node, "info") and node.info else None
        content = node.content or ""
        return [
            CodeBlock(
                id=self._next_block_id(),
                language=language,
                content=content.rstrip("\n"),
            )
        ]

    def _transform_math(
        self,
        node: SyntaxTreeNode,
        parent: SyntaxTreeNode | None,
        index: int,
    ) -> list[MathBlock]:
        """Transform display math block."""
        content = node.content or ""

        # Check if followed by yap-speak paragraph (already marked for skipping)
        tts_text = ""
        if parent and index + 1 in self._skip_indices:
            next_node = parent.children[index + 1]
            tts_text = self._extract_speak_from_paragraph(next_node)

        audio_chunks: list[AudioChunk] = []
        if tts_text.strip():
            audio_chunks = [
                AudioChunk(
                    text=tts_text.strip(),
                    audio_block_idx=self._next_audio_idx(),
                    ast=[TextContent(content=tts_text.strip())],
                )
            ]

        return [
            MathBlock(
                id=self._next_block_id(),
                content=content.strip(),
                display_mode=True,
                audio_chunks=audio_chunks,
            )
        ]

    def _transform_table(self, node: SyntaxTreeNode) -> list[TableBlock]:
        """Transform table node."""
        headers: list[TableCell] = []
        rows: list[list[TableCell]] = []

        for child in node.children:
            if child.type == "thead":
                for tr in child.children:
                    for th in tr.children:
                        inline = th.children[0] if th.children else None
                        children = inline.children if inline else []
                        processor = InlineProcessor()
                        html, _ = processor.process(children)
                        ast = transform_inline_to_ast(children)
                        headers.append(TableCell(html=html, ast=ast))
            elif child.type == "tbody":
                for tr in child.children:
                    row: list[TableCell] = []
                    for td in tr.children:
                        inline = td.children[0] if td.children else None
                        children = inline.children if inline else []
                        processor = InlineProcessor()
                        html, _ = processor.process(children)
                        ast = transform_inline_to_ast(children)
                        row.append(TableCell(html=html, ast=ast))
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

    def _transform_html_block(self, node: SyntaxTreeNode) -> Sequence[ContentBlock]:
        """Handle html_block nodes — multi-line yap tags that markdown-it
        classifies as block-level HTML instead of inline.
        """
        content = (node.content or "").strip()

        show_match = re.match(r"<yap-show>(.*?)</yap-show>", content, re.DOTALL)
        if show_match:
            inner_md = show_match.group(1).strip()
            if not inner_md:
                return []
            saved_audio_idx = self._audio_idx_counter
            inner_tree = parse_markdown(inner_md)
            blocks: list[ContentBlock] = []
            for child in inner_tree.children:
                blocks.extend(self._transform_node(child, inner_tree))
            _strip_audio_recursive(blocks)
            self._audio_idx_counter = saved_audio_idx
            return blocks

        if re.match(r"<yap-speak>(.*?)</yap-speak>", content, re.DOTALL):
            return []

        return []


def _strip_audio_recursive(blocks: Sequence[ContentBlock]) -> None:
    """Remove all audio_chunks from blocks and their nested structures."""
    for block in blocks:
        block.audio_chunks.clear()
        match block:
            case ListBlock():
                for item in block.items:
                    item.audio_chunks.clear()
            case BlockquoteBlock():
                _strip_audio_recursive(block.blocks)
            case FootnotesBlock():
                for item in block.items:
                    item.audio_chunks.clear()
                    _strip_audio_recursive(item.blocks)


# === PUBLIC API ===


def transform_to_document(
    ast: SyntaxTreeNode,
    max_block_chars: int,
    soft_limit_mult: float,
    min_chunk_size: int,
) -> StructuredDocument:
    """Transform markdown AST to StructuredDocument."""
    return DocumentTransformer(
        max_block_chars=max_block_chars,
        soft_limit_mult=soft_limit_mult,
        min_chunk_size=min_chunk_size,
    ).transform(ast)

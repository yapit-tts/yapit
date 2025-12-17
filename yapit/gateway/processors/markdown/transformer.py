"""Transform markdown AST to StructuredDocument.

Walks the markdown-it-py SyntaxTreeNode and produces our structured JSON format
with both HTML and AST representations for prose blocks.
"""

import re

from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode
from mdit_py_plugins.dollarmath import dollarmath_plugin

from yapit.gateway.processors.markdown.models import (
    BlockquoteBlock,
    CodeBlock,
    CodeSpanContent,
    ContentBlock,
    EmphasisContent,
    HeadingBlock,
    InlineContent,
    InlineImageContent,
    LinkContent,
    ListBlock,
    ListItem,
    MathBlock,
    ParagraphBlock,
    StrongContent,
    StructuredDocument,
    TableBlock,
    TextContent,
    ThematicBreak,
)


class DocumentTransformer:
    """Transforms markdown AST to StructuredDocument."""

    def __init__(self, max_block_chars: int = 150):
        self.max_block_chars = max_block_chars
        self._block_counter = 0
        self._audio_idx_counter = 0
        self._visual_group_counter = 0
        self._md = self._create_renderer()

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

    def _next_audio_idx(self) -> int:
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
        blocks = self._transform_children(ast)
        return StructuredDocument(blocks=blocks)

    def _transform_children(self, node: SyntaxTreeNode) -> list[ContentBlock]:
        """Transform all children of a node."""
        blocks: list[ContentBlock] = []
        for child in node.children:
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
        level = int(node.tag[1])  # h1 -> 1, h2 -> 2, etc.
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
                audio_block_idx=self._next_audio_idx(),
            )
        ]

    def _transform_paragraph(self, node: SyntaxTreeNode) -> list[ParagraphBlock]:
        """Transform paragraph node, splitting if too long."""
        inline = node.children[0] if node.children else None
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
                    audio_block_idx=self._next_audio_idx(),
                )
            ]

        # Split large paragraphs
        return self._split_paragraph(inline, plain_text)

    def _split_paragraph(self, inline: SyntaxTreeNode | None, plain_text: str) -> list[ParagraphBlock]:
        """Split a large paragraph into multiple blocks at sentence boundaries."""
        chunks = self._split_text_into_chunks(plain_text)
        blocks = []

        # All blocks from same paragraph share a visual_group_id
        visual_group_id = self._next_visual_group_id()

        for chunk in chunks:
            # For split blocks, we use plain text as both HTML and content
            # This is a simplification - we lose formatting in split blocks
            # but it's acceptable for v0
            blocks.append(
                ParagraphBlock(
                    id=self._next_block_id(),
                    html=chunk,
                    ast=[TextContent(content=chunk)],
                    plain_text=chunk,
                    audio_block_idx=self._next_audio_idx(),
                    visual_group_id=visual_group_id,
                )
            )

        return blocks

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
        """Transform list (bullet or ordered) node."""
        ordered = node.type == "ordered_list"
        start = node.attrs.get("start") if ordered else None

        items = []
        plain_texts = []

        for list_item in node.children:
            # List items contain paragraphs
            item_html_parts = []
            item_ast: list[InlineContent] = []
            item_plain_parts = []

            for child in list_item.children:
                if child.type == "paragraph":
                    inline = child.children[0] if child.children else None
                    item_html_parts.append(self._render_inline_html(inline))
                    item_ast.extend(self._transform_inline(inline))
                    item_plain_parts.append(self._extract_plain_text(inline))

            items.append(
                ListItem(
                    html=" ".join(item_html_parts),
                    ast=item_ast,
                    plain_text=" ".join(item_plain_parts),
                )
            )
            plain_texts.append(" ".join(item_plain_parts))

        return [
            ListBlock(
                id=self._next_block_id(),
                ordered=ordered,
                start=start,
                items=items,
                plain_text=" ".join(plain_texts),
                audio_block_idx=self._next_audio_idx(),
            )
        ]

    def _transform_blockquote(self, node: SyntaxTreeNode) -> list[BlockquoteBlock]:
        """Transform blockquote node."""
        # Recursively transform children
        inner_blocks = self._transform_children(node)

        # Collect plain text from inner blocks
        plain_texts = []
        for block in inner_blocks:
            if hasattr(block, "plain_text") and block.plain_text:
                plain_texts.append(block.plain_text)

        return [
            BlockquoteBlock(
                id=self._next_block_id(),
                blocks=inner_blocks,
                plain_text=" ".join(plain_texts),
                audio_block_idx=self._next_audio_idx(),
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

        return [
            MathBlock(
                id=self._next_block_id(),
                content=content.strip(),
                display_mode=True,
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
        """Render inline content to HTML string."""
        if not inline or not inline.children:
            return ""

        # Reconstruct the inline content and render
        # This is a bit hacky but works for now
        parts = []
        for child in inline.children:
            parts.append(self._render_inline_node_html(child))
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
            alt = node.attrs.get("alt", "")
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
        """Transform inline content to AST representation."""
        if not inline or not inline.children:
            return []

        result: list[InlineContent] = []
        for child in inline.children:
            result.extend(self._transform_inline_node(child))
        return result

    def _transform_inline_node(self, node: SyntaxTreeNode) -> list[InlineContent]:
        """Transform a single inline node to InlineContent."""
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
                    href=node.attrs.get("href", ""),
                    title=node.attrs.get("title"),
                    content=inner,
                )
            ]
        elif node.type == "image":
            return [
                InlineImageContent(
                    src=node.attrs.get("src", ""),
                    alt=node.attrs.get("alt", ""),
                )
            ]
        elif node.type == "softbreak":
            return [TextContent(content=" ")]
        elif node.type == "hardbreak":
            return [TextContent(content="\n")]
        else:
            # Unknown type, return as text if has content
            if node.content:
                return [TextContent(content=node.content)]
            return []

    def _extract_plain_text(self, inline: SyntaxTreeNode | None) -> str:
        """Extract plain text from inline content (for TTS)."""
        if not inline or not inline.children:
            return ""

        parts = []
        for child in inline.children:
            parts.append(self._extract_plain_text_node(child))
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
            return node.attrs.get("alt", "")
        elif node.type in ("softbreak", "hardbreak"):
            return " "
        elif node.type == "math_inline":
            # Skip inline math for TTS
            return ""
        else:
            return node.content or ""


def transform_to_document(ast: SyntaxTreeNode, **kwargs) -> StructuredDocument:
    """Transform markdown AST to StructuredDocument."""
    return DocumentTransformer(**kwargs).transform(ast)

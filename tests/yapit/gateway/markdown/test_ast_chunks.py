import pytest

from yapit.gateway.markdown import DocumentTransformer, parse_markdown
from yapit.gateway.markdown.models import (
    BlockquoteBlock,
    FootnotesBlock,
    HeadingBlock,
    ImageBlock,
    LinkContent,
    ListBlock,
    ListContent,
    MathBlock,
    ParagraphBlock,
    TableBlock,
    TextContent,
)
from yapit.gateway.markdown.transformer import (
    get_inline_length,
    slice_ast,
)

from .conftest import ast_contains, ast_text

DEFAULT_MAX_BLOCK_CHARS = 250
DEFAULT_SOFT_LIMIT_MULT = 1.3
DEFAULT_MIN_CHUNK_SIZE = 40


def transform(md: str, **kwargs):
    ast = parse_markdown(md)
    return DocumentTransformer(
        max_block_chars=kwargs.get("max_block_chars", DEFAULT_MAX_BLOCK_CHARS),
        soft_limit_mult=kwargs.get("soft_limit_mult", DEFAULT_SOFT_LIMIT_MULT),
        min_chunk_size=kwargs.get("min_chunk_size", DEFAULT_MIN_CHUNK_SIZE),
    ).transform(ast)


def collect_display_text(doc) -> str:
    """Collect all display text from document blocks for content-presence checks."""
    texts = []
    for block in doc.blocks:
        if hasattr(block, "ast"):
            texts.append(ast_text(block.ast))
        if hasattr(block, "items"):
            for item in block.items:
                if hasattr(item, "ast"):
                    texts.append(ast_text(item.ast))
                if hasattr(item, "blocks"):  # FootnoteItem
                    for nested in item.blocks:
                        if hasattr(nested, "ast"):
                            texts.append(ast_text(nested.ast))
        if hasattr(block, "blocks"):  # BlockquoteBlock
            for nested in block.blocks:
                if hasattr(nested, "ast"):
                    texts.append(ast_text(nested.ast))
    return " ".join(texts)


# === 1. AUDIO CHUNK AST ===


class TestChunkAst:
    """Chunk AST carries all information needed for frontend rendering."""

    def test_simple_paragraph_single_chunk(self):
        """Single-chunk paragraph: chunk.ast == block.ast."""
        doc = transform("Hello world.")
        block = doc.blocks[0]
        assert isinstance(block, ParagraphBlock)
        assert len(block.audio_chunks) == 1
        chunk = block.audio_chunks[0]
        assert chunk.ast, "chunk.ast should be populated"
        assert chunk.ast == block.ast

    def test_paragraph_with_formatting(self):
        """Paragraph with bold/italic: chunk AST preserves formatting."""
        doc = transform("This is **bold** and *italic* text.")
        block = doc.blocks[0]
        chunk = block.audio_chunks[0]
        assert chunk.ast
        assert ast_contains(chunk.ast, "strong")
        assert ast_contains(chunk.ast, "emphasis")
        assert "bold" in ast_text(chunk.ast)
        assert "italic" in ast_text(chunk.ast)

    def test_paragraph_with_math(self):
        """Paragraph with inline math: chunk AST includes MathInlineContent."""
        doc = transform(r"The value $\alpha$ is important.")
        block = doc.blocks[0]
        chunk = block.audio_chunks[0]
        assert chunk.ast
        assert ast_contains(chunk.ast, "math_inline")
        assert r"\alpha" in ast_text(chunk.ast)

    def test_paragraph_with_link(self):
        """Paragraph with link: chunk AST includes LinkContent."""
        doc = transform("Visit [Google](https://google.com) now.")
        block = doc.blocks[0]
        chunk = block.audio_chunks[0]
        assert chunk.ast
        link = next(n for n in chunk.ast if isinstance(n, LinkContent))
        assert link.href == "https://google.com"

    def test_paragraph_with_yap_show(self):
        """Paragraph with yap-show: chunk AST includes ShowContent."""
        doc = transform("Text <yap-show>[1, 2]</yap-show> more.")
        block = doc.blocks[0]
        chunk = block.audio_chunks[0]
        assert chunk.ast
        assert ast_contains(chunk.ast, "show")
        assert "[1, 2]" in ast_text(chunk.ast)

    def test_paragraph_with_yap_speak(self):
        """Paragraph with yap-speak: chunk AST includes SpeakContent."""
        doc = transform(r"The $\alpha$<yap-speak>alpha</yap-speak> value.")
        block = doc.blocks[0]
        chunk = block.audio_chunks[0]
        assert chunk.ast
        assert ast_contains(chunk.ast, "math_inline")
        assert ast_contains(chunk.ast, "speak")

    def test_split_paragraph_each_chunk_has_ast(self):
        """Multi-chunk paragraph: each chunk has its own sliced AST."""
        doc = transform(
            "First sentence with **bold**. Second sentence with *italic*. Third sentence here.",
            max_block_chars=40,
        )
        block = doc.blocks[0]
        assert len(block.audio_chunks) > 1, "Should split into multiple chunks"
        for chunk in block.audio_chunks:
            assert chunk.ast, f"Chunk {chunk.audio_block_idx} missing ast"
            assert ast_text(chunk.ast), f"Chunk {chunk.audio_block_idx} has empty text"

    def test_heading_chunk_has_ast(self):
        """Heading: chunk AST matches block AST."""
        doc = transform("# My **Bold** Heading")
        block = doc.blocks[0]
        assert isinstance(block, HeadingBlock)
        assert len(block.audio_chunks) == 1
        chunk = block.audio_chunks[0]
        assert chunk.ast
        assert chunk.ast == block.ast

    def test_list_item_chunk_has_ast(self):
        """List item: chunk AST populated."""
        doc = transform("- Item with **bold** text")
        block = doc.blocks[0]
        assert isinstance(block, ListBlock)
        item = block.items[0]
        assert len(item.audio_chunks) == 1
        chunk = item.audio_chunks[0]
        assert chunk.ast
        assert ast_contains(chunk.ast, "strong")

    def test_split_list_item_chunks_have_ast(self):
        """Split list item: each chunk has sliced AST."""
        doc = transform(
            "- First sentence here. Second sentence here. Third sentence here.",
            max_block_chars=30,
        )
        block = doc.blocks[0]
        assert isinstance(block, ListBlock)
        item = block.items[0]
        assert len(item.audio_chunks) > 1
        for chunk in item.audio_chunks:
            assert chunk.ast, f"List item chunk {chunk.audio_block_idx} missing ast"

    def test_image_caption_chunk_has_ast(self):
        """Image caption: chunk AST populated."""
        doc = transform("![alt](img.png)<yap-cap>Caption with **bold**</yap-cap>")
        block = doc.blocks[0]
        assert isinstance(block, ImageBlock)
        assert len(block.audio_chunks) == 1
        chunk = block.audio_chunks[0]
        assert chunk.ast
        assert ast_contains(chunk.ast, "strong")

    def test_image_alt_text_chunk_has_ast(self):
        """Image with alt text (no caption): chunk AST is TextContent."""
        doc = transform("![A cute cat](cat.png)")
        block = doc.blocks[0]
        assert isinstance(block, ImageBlock)
        assert len(block.audio_chunks) == 1
        chunk = block.audio_chunks[0]
        assert chunk.ast
        assert ast_text(chunk.ast) == "A cute cat"

    def test_callout_title_chunk_has_ast(self):
        """Callout title: chunk AST populated (plain text)."""
        doc = transform("> [!BLUE] Definition 1.2\n> Content here.")
        block = doc.blocks[0]
        assert block.type == "blockquote"
        assert len(block.audio_chunks) == 1
        chunk = block.audio_chunks[0]
        assert chunk.ast
        assert ast_text(chunk.ast) == "Definition 1.2"

    def test_math_block_speak_chunk_has_ast(self):
        """Math block with yap-speak: chunk AST is the speak text."""
        doc = transform("$$E = mc^2$$\n<yap-speak>E equals m c squared</yap-speak>")
        math_blocks = [b for b in doc.blocks if isinstance(b, MathBlock)]
        assert len(math_blocks) == 1
        block = math_blocks[0]
        assert len(block.audio_chunks) == 1
        chunk = block.audio_chunks[0]
        assert chunk.ast
        assert ast_text(chunk.ast) == "E equals m c squared"

    def test_math_block_long_speak_is_split(self):
        """Math block with yap-speak exceeding max_block_chars must be split."""
        long_speak = (
            "The probability of a policy pi is a categorical distribution "
            "parameterized by pi zero, where pi zero is the softmax of negative G. "
            "The expected free energy G of pi is the negative expected divergence "
            "between the approximate posterior and the prior over future states, "
            "minus the expected log probability of future observations given preferences."
        )
        assert len(long_speak) > DEFAULT_MAX_BLOCK_CHARS
        md = f"$$P(\\pi) = \\text{{Cat}}(\\pi_0)$$\n<yap-speak>{long_speak}</yap-speak>"
        doc = transform(md)
        math_blocks = [b for b in doc.blocks if isinstance(b, MathBlock)]
        assert len(math_blocks) == 1
        block = math_blocks[0]
        soft_max = int(DEFAULT_MAX_BLOCK_CHARS * DEFAULT_SOFT_LIMIT_MULT)
        assert len(block.audio_chunks) > 1, (
            f"Speak text of {len(long_speak)} chars should be split (max_block_chars={DEFAULT_MAX_BLOCK_CHARS})"
        )
        for chunk in block.audio_chunks:
            assert len(chunk.text) <= soft_max, f"Chunk len {len(chunk.text)} exceeds soft_max {soft_max}"

    def test_math_block_speak_respects_max_block_chars(self):
        """No audio block from math yap-speak should exceed soft_max, regardless of input size."""
        huge_speak = "A " * 1000  # 2000 chars of simple text
        md = f"$$x = 1$$\n<yap-speak>{huge_speak.strip()}</yap-speak>"
        doc = transform(md)
        audio_blocks = doc.get_audio_blocks()
        soft_max = int(DEFAULT_MAX_BLOCK_CHARS * DEFAULT_SOFT_LIMIT_MULT)
        for i, text in enumerate(audio_blocks):
            assert len(text) <= soft_max, f"Audio block {i} has {len(text)} chars, exceeds soft_max {soft_max}"

    def test_footnote_content_chunk_has_ast(self):
        """Footnote content paragraph: chunk AST populated."""
        doc = transform("Text[^1].\n\n[^1]: Footnote with **bold** content.")
        footnotes = doc.blocks[1]
        assert footnotes.type == "footnotes"
        item = footnotes.items[0]
        content_block = item.blocks[0]
        assert len(content_block.audio_chunks) == 1
        chunk = content_block.audio_chunks[0]
        assert chunk.ast
        assert ast_contains(chunk.ast, "strong")

    def test_blockquote_nested_paragraph_chunk_has_ast(self):
        """Blockquote nested paragraph: chunk AST populated."""
        doc = transform("> This is **quoted** text.")
        block = doc.blocks[0]
        assert block.type == "blockquote"
        nested = block.blocks[0]
        assert nested.type == "paragraph"
        chunk = nested.audio_chunks[0]
        assert chunk.ast
        assert ast_contains(chunk.ast, "strong")


# === 2. TABLE CELL AST ===


class TestTableCellAst:
    """TableBlock cells should have AST."""

    def test_table_headers_have_ast(self):
        """Table headers have ast field with correct content."""
        doc = transform("| **Name** | Value |\n|---|---|\n| a | b |")
        block = doc.blocks[0]
        assert isinstance(block, TableBlock)
        header = block.headers[0]
        assert header.ast
        assert ast_contains(header.ast, "strong")

    def test_table_cells_have_ast(self):
        """Table cells have ast field with correct content."""
        doc = transform("| A | B |\n|---|---|\n| *italic* | `code` |")
        block = doc.blocks[0]
        assert isinstance(block, TableBlock)
        cell = block.rows[0][0]
        assert cell.ast
        assert ast_contains(cell.ast, "emphasis")

    def test_table_cell_with_math(self):
        """Table cell with inline math has MathInlineContent in AST."""
        doc = transform(r"| $\alpha$ | Value |" + "\n|---|---|\n| 1 | 2 |")
        block = doc.blocks[0]
        header = block.headers[0]
        assert header.ast
        assert ast_contains(header.ast, "math_inline")

    def test_table_cell_with_link(self):
        """Table cell with link has LinkContent in AST."""
        doc = transform("| A |\n|---|\n| [link](url) |")
        block = doc.blocks[0]
        cell = block.rows[0][0]
        assert cell.ast
        link = next(n for n in cell.ast if isinstance(n, LinkContent))
        assert link.href == "url"


# === 3. MULTI-LINE YAP-SHOW (html_block handling) ===


class TestMultiLineYapShow:
    """Multi-line <yap-show> blocks (classified as html_block by markdown-it)."""

    def test_multiline_yap_show_not_dropped(self):
        """Multi-line yap-show content should appear in document blocks."""
        md = "<yap-show>\n© 2024 Google. All rights reserved.\n</yap-show>\n\n# Title"
        doc = transform(md)
        assert len(doc.blocks) >= 2
        assert "2024 Google" in collect_display_text(doc)

    def test_multiline_yap_show_no_audio(self):
        """Multi-line yap-show content should have no audio chunks."""
        md = "<yap-show>\n© 2024 Google.\n</yap-show>"
        doc = transform(md)
        assert len(doc.blocks) >= 1
        for block in doc.blocks:
            if hasattr(block, "audio_chunks"):
                assert len(block.audio_chunks) == 0, (
                    f"Block from yap-show should have no audio, got {block.audio_chunks}"
                )

    def test_multiline_yap_show_markdown_formatting(self):
        """Multi-line yap-show with markdown formatting produces correct AST."""
        md = "<yap-show>\nThis has **bold** and *italic* text.\n</yap-show>"
        doc = transform(md)
        assert len(doc.blocks) >= 1
        block = doc.blocks[0]
        assert ast_contains(block.ast, "strong")
        assert ast_contains(block.ast, "emphasis")

    def test_multiline_yap_show_with_math(self):
        """Multi-line yap-show with LaTeX has math in AST."""
        md = "<yap-show>\nThe formula $E=mc^2$ is famous.\n</yap-show>"
        doc = transform(md)
        assert len(doc.blocks) >= 1
        display = collect_display_text(doc)
        assert "E=mc^2" in display

    def test_multiline_yap_show_with_list(self):
        """Multi-line yap-show with list items."""
        md = "<yap-show>\n- Item A\n- Item B\n</yap-show>"
        doc = transform(md)
        list_blocks = [b for b in doc.blocks if b.type == "list"]
        assert len(list_blocks) == 1
        for item in list_blocks[0].items:
            assert len(item.audio_chunks) == 0

    def test_multiline_yap_show_with_heading(self):
        """Multi-line yap-show with heading and blank lines."""
        md = "<yap-show>\n## Credits\n\nAuthor: Jane Doe\n</yap-show>"
        doc = transform(md)
        heading_blocks = [b for b in doc.blocks if b.type == "heading"]
        assert len(heading_blocks) == 1
        assert heading_blocks[0].audio_chunks == []

    def test_multiline_yap_speak_dropped(self):
        """Multi-line yap-speak should be entirely dropped (TTS-only, not displayed)."""
        md = "<yap-speak>\nThis is spoken only.\n</yap-speak>\n\n# Title"
        doc = transform(md)
        display = collect_display_text(doc)
        assert "spoken only" not in display

    def test_multiline_yap_show_between_content(self):
        """Multi-line yap-show between regular content blocks."""
        md = "# Title\n\n<yap-show>\n© 2024 License info.\n</yap-show>\n\nRegular paragraph."
        doc = transform(md)
        audio = doc.get_audio_blocks()
        assert any("Title" in t for t in audio)
        assert any("Regular paragraph" in t for t in audio)
        assert not any("License" in t for t in audio)


# === 4. HTML_INLINE SANITIZATION ===


class TestHtmlInlineSanitization:
    """Raw html_inline nodes should be dropped from AST."""

    def test_raw_html_not_in_ast(self):
        """Raw HTML should not appear in AST nodes."""
        doc = transform("Text <img src=x onerror=alert(1)> here.")
        block = doc.blocks[0]
        for node in block.ast:
            assert node.type in (
                "text",
                "code_span",
                "strong",
                "emphasis",
                "link",
                "inline_image",
                "math_inline",
                "speak",
                "show",
                "hardbreak",
                "footnote_ref",
            ), f"Unexpected AST node type: {node.type}"

    def test_yap_tags_still_work(self):
        """Yap tags (our html_inline) should still function normally."""
        doc = transform("Text <yap-show>[1]</yap-show> more.")
        block = doc.blocks[0]
        assert ast_contains(block.ast, "show")
        assert "[1]" in ast_text(block.ast)


# === 5. HARDBREAK AST ===


class TestHardbreakAst:
    """Hardbreaks produce HardbreakContent (not TextContent like softbreaks)."""

    def test_hardbreak_produces_hardbreak_content(self):
        """Two trailing spaces + newline → HardbreakContent in AST."""
        doc = transform("Line one  \nLine two")
        block = doc.blocks[0]
        types = [n.type for n in block.ast]
        assert "hardbreak" in types

    def test_softbreak_still_produces_space(self):
        """Regular newline (softbreak) still produces TextContent(' ')."""
        doc = transform("Line one\nLine two")
        block = doc.blocks[0]
        types = [n.type for n in block.ast]
        assert "hardbreak" not in types

    def test_hardbreak_chunk_ast_matches_block(self):
        """Single-chunk paragraph with hardbreak: chunk.ast == block.ast."""
        doc = transform("Before break  \nAfter break")
        block = doc.blocks[0]
        assert len(block.audio_chunks) == 1
        chunk = block.audio_chunks[0]
        assert chunk.ast == block.ast


# === 6. IMAGE CAPTION AST ===


class TestImageCaptionAst:
    """Image captions go through split_with_spans — verify chunk ASTs are correct."""

    def test_single_chunk_caption(self):
        """Single-chunk caption: chunk AST has correct content."""
        doc = transform("![alt](img.png)<yap-cap>Caption with **bold**</yap-cap>")
        block = doc.blocks[0]
        assert isinstance(block, ImageBlock)
        assert len(block.audio_chunks) == 1
        chunk = block.audio_chunks[0]
        assert ast_contains(chunk.ast, "strong")
        assert "Caption with" in ast_text(chunk.ast)

    def test_multi_chunk_caption(self):
        """Multi-chunk caption: each chunk has non-empty AST."""
        doc = transform(
            "![alt](img.png)<yap-cap>First sentence of the caption here. "
            "Second sentence with *italic* formatting here too.</yap-cap>",
            max_block_chars=40,
        )
        block = doc.blocks[0]
        assert isinstance(block, ImageBlock)
        assert len(block.audio_chunks) > 1, "Caption should split into multiple chunks"
        for chunk in block.audio_chunks:
            assert chunk.ast, f"Caption chunk {chunk.audio_block_idx} missing ast"
            assert ast_text(chunk.ast), f"Caption chunk {chunk.audio_block_idx} has empty text"

    def test_alt_text_fallback(self):
        """Image with alt text (no caption): chunk AST is the alt text."""
        doc = transform("![A descriptive alt text](img.png)")
        block = doc.blocks[0]
        assert isinstance(block, ImageBlock)
        assert len(block.audio_chunks) == 1
        chunk = block.audio_chunks[0]
        assert ast_text(chunk.ast) == "A descriptive alt text"

    def test_caption_with_math(self):
        """Caption with inline math: chunk AST includes MathInlineContent."""
        doc = transform(r"![alt](img.png)<yap-cap>Shows $\alpha$ decay</yap-cap>")
        block = doc.blocks[0]
        assert isinstance(block, ImageBlock)
        chunk = block.audio_chunks[0]
        assert ast_contains(chunk.ast, "math_inline")
        assert r"\alpha" in ast_text(chunk.ast)
        assert "Shows" in ast_text(chunk.ast)


# === 7. YAP-SHOW EDGE CASES ===


class TestYapShowEdgeCases:
    """Edge cases for multi-line yap-show/yap-speak handling."""

    def test_unclosed_yap_show_still_renders(self):
        """Unclosed <yap-show> at end of document includes content (no audio)."""
        md = "# Title\n\n<yap-show>\nUnclosed copyright notice."
        doc = transform(md)
        display = collect_display_text(doc)
        assert "copyright notice" in display

    def test_yap_show_with_nested_blockquote(self):
        """yap-show containing a blockquote strips audio from nested blocks."""
        md = "<yap-show>\n> Quoted attribution text.\n</yap-show>"
        doc = transform(md)
        bq_blocks = [b for b in doc.blocks if isinstance(b, BlockquoteBlock)]
        assert len(bq_blocks) == 1
        bq = bq_blocks[0]
        assert len(bq.audio_chunks) == 0
        for nested in bq.blocks:
            assert len(nested.audio_chunks) == 0

    def test_yap_show_with_nested_list(self):
        """yap-show containing a list strips audio from all items."""
        md = "<yap-show>\n- Author A\n- Author B\n- Author C\n</yap-show>"
        doc = transform(md)
        list_blocks = [b for b in doc.blocks if isinstance(b, ListBlock)]
        assert len(list_blocks) == 1
        for item in list_blocks[0].items:
            assert len(item.audio_chunks) == 0

    def test_yap_show_with_footnote_content(self):
        """yap-show containing footnote-like content renders without audio."""
        md = "<yap-show>\nSee reference[^1] for details.\n\n[^1]: Full citation here.\n</yap-show>"
        doc = transform(md)
        for block in doc.blocks:
            if hasattr(block, "audio_chunks"):
                assert len(block.audio_chunks) == 0, f"Block type {block.type} inside yap-show should have no audio"
            if isinstance(block, FootnotesBlock):
                for item in block.items:
                    assert len(item.audio_chunks) == 0
                    for nested in item.blocks:
                        assert len(nested.audio_chunks) == 0

    def test_yap_show_does_not_consume_audio_indices(self):
        """yap-show content must not leave gaps in audio_block_idx sequence."""
        md = "Before.\n\n<yap-show>\nDisplay only text.\n</yap-show>\n\nAfter."
        doc = transform(md)
        indices = []
        for block in doc.blocks:
            for chunk in block.audio_chunks:
                indices.append(chunk.audio_block_idx)
        assert indices == list(range(len(indices))), f"Audio indices should be contiguous, got {indices}"

    def test_non_yap_html_block_silently_dropped(self):
        """Raw HTML blocks (not yap tags) are silently dropped."""
        md = "# Title\n\n<div class='custom'>Some HTML</div>\n\nParagraph."
        doc = transform(md)
        display = collect_display_text(doc)
        assert "custom" not in display
        assert "Title" in display
        assert "Paragraph" in display

    @pytest.mark.xfail(
        reason="Multi-block <yap-speak> (with blank lines) leaks intermediate nodes. "
        "Accumulation logic only handles yap-show. Low priority — Gemini rarely "
        "produces multi-line yap-speak with blank lines.",
        strict=True,
    )
    def test_multiblock_yap_speak_dropped(self):
        """Multi-block yap-speak (blank lines inside) should drop all content."""
        md = "# Title\n\n<yap-speak>\nSpoken paragraph one.\n\nSpoken paragraph two.\n</yap-speak>\n\nVisible."
        doc = transform(md)
        display = collect_display_text(doc)
        assert "Spoken paragraph" not in display
        assert "Title" in display
        assert "Visible" in display


# === 8. NESTED LIST AST ===


class TestNestedListAst:
    """Nested lists within list items must be represented in item.ast as ListContent nodes.

    The TTS text for nested items is flattened into the parent item's audio chunks
    (joined with " "), so ListContent's TTS length must match that joined text exactly.
    """

    def test_nested_list_appears_in_item_ast(self):
        """item.ast should contain a ListContent node for nested bullets."""
        doc = transform("- Top item\n  - Sub A\n  - Sub B")
        block = doc.blocks[0]
        assert isinstance(block, ListBlock)
        item = block.items[0]
        list_nodes = [n for n in item.ast if isinstance(n, ListContent)]
        assert len(list_nodes) == 1, f"Expected 1 ListContent in ast, got {len(list_nodes)}"

    def test_nested_list_content_structure(self):
        """ListContent should have correct ordered flag and item content."""
        doc = transform("- Parent\n  - Child A\n  - Child B")
        block = doc.blocks[0]
        item = block.items[0]
        list_node = next(n for n in item.ast if isinstance(n, ListContent))
        assert list_node.ordered is False
        assert len(list_node.items) == 2
        assert any(getattr(n, "content", None) == "Child A" for n in list_node.items[0])
        assert any(getattr(n, "content", None) == "Child B" for n in list_node.items[1])

    def test_nested_ordered_list(self):
        """Nested ordered list has ordered=True and correct start."""
        doc = transform("- Parent\n  1. First\n  2. Second")
        block = doc.blocks[0]
        item = block.items[0]
        list_node = next(n for n in item.ast if isinstance(n, ListContent))
        assert list_node.ordered is True
        assert len(list_node.items) == 2

    def test_nested_list_with_formatting(self):
        """Nested list items with formatting preserve AST structure."""
        doc = transform("- Parent\n  - **Bold child**\n  - *Italic child*")
        block = doc.blocks[0]
        item = block.items[0]
        list_node = next(n for n in item.ast if isinstance(n, ListContent))
        # First nested item should have StrongContent
        assert ast_contains(list_node.items[0], "strong")
        assert "Bold child" in ast_text(list_node.items[0])
        # Second nested item should have EmphasisContent
        assert ast_contains(list_node.items[1], "emphasis")
        assert "Italic child" in ast_text(list_node.items[1])

    def test_nested_list_tts_length_matches(self):
        """get_inline_length of item.ast must equal len(full_tts) for correct slicing."""
        doc = transform("- Parent text\n  - Sub A\n  - Sub B")
        block = doc.blocks[0]
        item = block.items[0]
        tts = " ".join(c.text for c in item.audio_chunks)
        ast_len = sum(get_inline_length(n) for n in item.ast)
        assert ast_len == len(tts), f"AST length {ast_len} != TTS length {len(tts)} for tts={tts!r}"

    def test_nested_list_slice_atomic_at_start(self):
        """ListContent is atomic — included whole when slice starts at position 0."""
        node = ListContent(
            ordered=False,
            items=[
                [TextContent(content="A")],
                [TextContent(content="B")],
            ],
        )
        length = get_inline_length(node)
        assert length == 3
        result = slice_ast([node], 0, 1)
        assert len(result) == 1
        assert isinstance(result[0], ListContent)
        assert len(result[0].items) == 2  # full list, not sliced

    def test_nested_list_slice_atomic_excludes_later(self):
        """ListContent is excluded from chunks that don't start at its position."""
        node = ListContent(
            ordered=False,
            items=[
                [TextContent(content="Alpha")],
                [TextContent(content="Beta")],
            ],
        )
        result = slice_ast([node], 3, 10)
        assert result == []

    def test_nested_list_with_preceding_text_sliced(self):
        """When text precedes ListContent, slicing past text excludes the list."""
        ast = [
            TextContent(content="Hello"),  # pos 0..5
            TextContent(content=" "),  # pos 5..6
            ListContent(
                ordered=False,
                items=[  # pos 6..9 (A + space + B)
                    [TextContent(content="A")],
                    [TextContent(content="B")],
                ],
            ),
        ]
        # Slice just "Hello " — no list
        result = slice_ast(ast, 0, 6)
        assert not any(isinstance(n, ListContent) for n in result)
        # Slice starting at list — gets full list
        result = slice_ast(ast, 6, 9)
        list_nodes = [n for n in result if isinstance(n, ListContent)]
        assert len(list_nodes) == 1
        assert len(list_nodes[0].items) == 2

    def test_nested_list_in_split_item(self):
        """List item with nested list that gets split: paragraph and nested list
        produce separate chunks so highlight boundaries align with visual boundaries.
        """
        long_text = "A very long parent text that should definitely cause splitting. "
        md = f"- {long_text}\n  - Sub item one\n  - Sub item two"
        doc = transform(md, max_block_chars=40)
        block = doc.blocks[0]
        assert isinstance(block, ListBlock)
        item = block.items[0]
        assert len(item.audio_chunks) > 1, "Item should be split into multiple chunks"
        full_text = " ".join(c.text for c in item.audio_chunks)
        assert "parent text" in full_text
        assert "Sub item" in full_text
        has_list = any(any(isinstance(n, ListContent) for n in chunk.ast) for chunk in item.audio_chunks)
        assert has_list, "At least one chunk should contain the nested list"

    def test_nested_list_chunks_separated_from_paragraph(self):
        """Paragraph and nested list are split independently — no chunk straddles both."""
        md = "- Parent paragraph text here\n  - Sub A\n  - Sub B"
        doc = transform(md, max_block_chars=150)
        block = doc.blocks[0]
        assert isinstance(block, ListBlock)
        item = block.items[0]
        assert len(item.audio_chunks) == 2
        para_chunk, list_chunk = item.audio_chunks
        assert not any(isinstance(n, ListContent) for n in para_chunk.ast)
        assert "Parent" in para_chunk.text
        assert any(isinstance(n, ListContent) for n in list_chunk.ast)
        assert "Sub A" in list_chunk.text
        for chunk in item.audio_chunks:
            has_text = any(isinstance(n, TextContent) and n.content.strip() for n in chunk.ast)
            has_list = any(isinstance(n, ListContent) for n in chunk.ast)
            assert not (has_text and has_list), f"Chunk should not straddle paragraph and nested list: {chunk.text!r}"

    def test_deeply_nested_list(self):
        """Three levels of nesting: list > nested list > deeper nested list."""
        md = "- Top\n  - Mid\n    - Deep"
        doc = transform(md)
        block = doc.blocks[0]
        assert isinstance(block, ListBlock)
        item = block.items[0]
        list_nodes = [n for n in item.ast if isinstance(n, ListContent)]
        assert len(list_nodes) == 1
        outer = list_nodes[0]
        mid_item = outer.items[0]
        inner_lists = [n for n in mid_item if isinstance(n, ListContent)]
        assert len(inner_lists) == 1, "Mid-level item should have a nested ListContent"
        # Deep level should have "Deep" text
        assert "Deep" in ast_text(inner_lists[0].items[0])

import pytest

from yapit.gateway.markdown import parse_markdown, transform_to_document
from yapit.gateway.markdown.models import (
    BlockquoteBlock,
    FootnotesBlock,
    HeadingBlock,
    ImageBlock,
    ListBlock,
    MathBlock,
    ParagraphBlock,
    TableBlock,
)
from yapit.gateway.markdown.transformer import render_ast_to_html

DEFAULT_MAX_BLOCK_CHARS = 250
DEFAULT_SOFT_LIMIT_MULT = 1.3
DEFAULT_MIN_CHUNK_SIZE = 40


def transform(md: str, **kwargs):
    ast = parse_markdown(md)
    return transform_to_document(
        ast,
        max_block_chars=kwargs.get("max_block_chars", DEFAULT_MAX_BLOCK_CHARS),
        soft_limit_mult=kwargs.get("soft_limit_mult", DEFAULT_SOFT_LIMIT_MULT),
        min_chunk_size=kwargs.get("min_chunk_size", DEFAULT_MIN_CHUNK_SIZE),
    )


# === 1. AUDIO CHUNK AST — ROUNDTRIP INVARIANT ===


class TestChunkAstRoundtrip:
    """Core invariant: render_ast_to_html(chunk.ast) ≈ chunk's HTML.

    This ensures the AST carries all information needed for the frontend
    to produce equivalent rendering.
    """

    def test_simple_paragraph_single_chunk(self):
        """Single-chunk paragraph: chunk.ast == block.ast."""
        doc = transform("Hello world.")
        block = doc.blocks[0]
        assert isinstance(block, ParagraphBlock)
        assert len(block.audio_chunks) == 1
        chunk = block.audio_chunks[0]
        assert chunk.ast, "chunk.ast should be populated"
        assert render_ast_to_html(chunk.ast) == block.html

    def test_paragraph_with_formatting(self):
        """Paragraph with bold/italic: chunk AST preserves formatting."""
        doc = transform("This is **bold** and *italic* text.")
        block = doc.blocks[0]
        chunk = block.audio_chunks[0]
        assert chunk.ast
        rendered = render_ast_to_html(chunk.ast)
        assert "<strong>bold</strong>" in rendered
        assert "<em>italic</em>" in rendered

    def test_paragraph_with_math(self):
        """Paragraph with inline math: chunk AST includes MathInlineContent."""
        doc = transform(r"The value $\alpha$ is important.")
        block = doc.blocks[0]
        chunk = block.audio_chunks[0]
        assert chunk.ast
        rendered = render_ast_to_html(chunk.ast)
        assert "math-inline" in rendered
        assert r"\alpha" in rendered

    def test_paragraph_with_link(self):
        """Paragraph with link: chunk AST includes LinkContent."""
        doc = transform("Visit [Google](https://google.com) now.")
        block = doc.blocks[0]
        chunk = block.audio_chunks[0]
        assert chunk.ast
        rendered = render_ast_to_html(chunk.ast)
        assert 'href="https://google.com"' in rendered

    def test_paragraph_with_yap_show(self):
        """Paragraph with yap-show: chunk AST includes ShowContent."""
        doc = transform("Text <yap-show>[1, 2]</yap-show> more.")
        block = doc.blocks[0]
        chunk = block.audio_chunks[0]
        assert chunk.ast
        rendered = render_ast_to_html(chunk.ast)
        assert "[1, 2]" in rendered

    def test_paragraph_with_yap_speak(self):
        """Paragraph with yap-speak: chunk AST includes SpeakContent (renders empty)."""
        doc = transform(r"The $\alpha$<yap-speak>alpha</yap-speak> value.")
        block = doc.blocks[0]
        chunk = block.audio_chunks[0]
        assert chunk.ast
        rendered = render_ast_to_html(chunk.ast)
        assert "math-inline" in rendered

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
            # Roundtrip: rendering the chunk AST should produce valid HTML
            rendered = render_ast_to_html(chunk.ast)
            assert rendered, f"Chunk {chunk.audio_block_idx} rendered to empty"

    def test_split_paragraph_roundtrip_matches_html(self):
        """Multi-chunk paragraph: chunk ASTs roundtrip to the span-wrapped HTML."""
        doc = transform(
            "First sentence here. Second sentence here. Third sentence here.",
            max_block_chars=30,
        )
        block = doc.blocks[0]
        assert len(block.audio_chunks) > 1

        # Reconstruct the full HTML from chunk ASTs
        parts = []
        for chunk in block.audio_chunks:
            chunk_html = render_ast_to_html(chunk.ast)
            parts.append(f'<span data-audio-idx="{chunk.audio_block_idx}">{chunk_html}</span>')
        reconstructed = " ".join(parts)
        assert reconstructed == block.html

    def test_heading_chunk_has_ast(self):
        """Heading: chunk AST matches block AST."""
        doc = transform("# My **Bold** Heading")
        block = doc.blocks[0]
        assert isinstance(block, HeadingBlock)
        assert len(block.audio_chunks) == 1
        chunk = block.audio_chunks[0]
        assert chunk.ast
        assert render_ast_to_html(chunk.ast) == block.html

    def test_list_item_chunk_has_ast(self):
        """List item: chunk AST populated."""
        doc = transform("- Item with **bold** text")
        block = doc.blocks[0]
        assert isinstance(block, ListBlock)
        item = block.items[0]
        assert len(item.audio_chunks) == 1
        chunk = item.audio_chunks[0]
        assert chunk.ast
        rendered = render_ast_to_html(chunk.ast)
        assert "<strong>bold</strong>" in rendered

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
        rendered = render_ast_to_html(chunk.ast)
        assert "<strong>bold</strong>" in rendered

    def test_image_alt_text_chunk_has_ast(self):
        """Image with alt text (no caption): chunk AST is TextContent."""
        doc = transform("![A cute cat](cat.png)")
        block = doc.blocks[0]
        assert isinstance(block, ImageBlock)
        assert len(block.audio_chunks) == 1
        chunk = block.audio_chunks[0]
        assert chunk.ast
        assert render_ast_to_html(chunk.ast) == "A cute cat"

    def test_callout_title_chunk_has_ast(self):
        """Callout title: chunk AST populated (plain text)."""
        doc = transform("> [!BLUE] Definition 1.2\n> Content here.")
        block = doc.blocks[0]
        assert block.type == "blockquote"
        assert len(block.audio_chunks) == 1
        chunk = block.audio_chunks[0]
        assert chunk.ast
        assert render_ast_to_html(chunk.ast) == "Definition 1.2"

    def test_math_block_speak_chunk_has_ast(self):
        """Math block with yap-speak: chunk AST is the speak text."""
        doc = transform("$$E = mc^2$$\n<yap-speak>E equals m c squared</yap-speak>")
        math_blocks = [b for b in doc.blocks if isinstance(b, MathBlock)]
        assert len(math_blocks) == 1
        block = math_blocks[0]
        assert len(block.audio_chunks) == 1
        chunk = block.audio_chunks[0]
        assert chunk.ast
        assert render_ast_to_html(chunk.ast) == "E equals m c squared"

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
        rendered = render_ast_to_html(chunk.ast)
        assert "<strong>bold</strong>" in rendered

    def test_blockquote_nested_paragraph_chunk_has_ast(self):
        """Blockquote nested paragraph: chunk AST populated."""
        doc = transform("> This is **quoted** text.")
        block = doc.blocks[0]
        assert block.type == "blockquote"
        nested = block.blocks[0]
        assert nested.type == "paragraph"
        chunk = nested.audio_chunks[0]
        assert chunk.ast
        rendered = render_ast_to_html(chunk.ast)
        assert "<strong>quoted</strong>" in rendered


# === 2. TABLE CELL AST ===


class TestTableCellAst:
    """TableBlock cells should have AST alongside HTML."""

    def test_table_headers_have_ast(self):
        """Table headers are TableCell objects with ast field."""
        doc = transform("| **Name** | Value |\n|---|---|\n| a | b |")
        block = doc.blocks[0]
        assert isinstance(block, TableBlock)
        # Headers should be TableCell objects, not raw strings
        header = block.headers[0]
        assert hasattr(header, "ast"), "Table header should have ast field"
        assert hasattr(header, "html"), "Table header should have html field"
        assert header.ast
        rendered = render_ast_to_html(header.ast)
        assert "<strong>Name</strong>" in rendered

    def test_table_cells_have_ast(self):
        """Table cells are TableCell objects with ast field."""
        doc = transform("| A | B |\n|---|---|\n| *italic* | `code` |")
        block = doc.blocks[0]
        assert isinstance(block, TableBlock)
        cell = block.rows[0][0]
        assert hasattr(cell, "ast"), "Table cell should have ast field"
        assert cell.ast
        rendered = render_ast_to_html(cell.ast)
        assert "<em>italic</em>" in rendered

    def test_table_cell_with_math(self):
        """Table cell with inline math has MathInlineContent in AST."""
        doc = transform(r"| $\alpha$ | Value |" + "\n|---|---|\n| 1 | 2 |")
        block = doc.blocks[0]
        header = block.headers[0]
        assert header.ast
        rendered = render_ast_to_html(header.ast)
        assert "math-inline" in rendered

    def test_table_cell_with_link(self):
        """Table cell with link has LinkContent in AST."""
        doc = transform("| A |\n|---|\n| [link](url) |")
        block = doc.blocks[0]
        cell = block.rows[0][0]
        assert cell.ast
        rendered = render_ast_to_html(cell.ast)
        assert 'href="url"' in rendered

    def test_table_cell_html_matches_ast(self):
        """Table cell HTML matches what render_ast_to_html produces."""
        doc = transform("| **bold** and *italic* |\n|---|\n| plain |")
        block = doc.blocks[0]
        header = block.headers[0]
        assert render_ast_to_html(header.ast) == header.html


# === 3. MULTI-LINE YAP-SHOW (html_block handling) ===


class TestMultiLineYapShow:
    """Multi-line <yap-show> blocks (classified as html_block by markdown-it)."""

    def test_multiline_yap_show_not_dropped(self):
        """Multi-line yap-show content should appear in document blocks."""
        md = "<yap-show>\n© 2024 Google. All rights reserved.\n</yap-show>\n\n# Title"
        doc = transform(md)
        # Should have the show content + heading (at minimum 2 blocks)
        assert len(doc.blocks) >= 2
        # The show content should appear somewhere
        all_html = " ".join(getattr(b, "html", "") for b in doc.blocks if hasattr(b, "html"))
        assert "2024 Google" in all_html

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
        """Multi-line yap-show with markdown formatting renders correctly."""
        md = "<yap-show>\nThis has **bold** and *italic* text.\n</yap-show>"
        doc = transform(md)
        assert len(doc.blocks) >= 1
        all_html = " ".join(getattr(b, "html", "") for b in doc.blocks if hasattr(b, "html"))
        assert "<strong>bold</strong>" in all_html
        assert "<em>italic</em>" in all_html

    def test_multiline_yap_show_with_math(self):
        """Multi-line yap-show with LaTeX renders math."""
        md = "<yap-show>\nThe formula $E=mc^2$ is famous.\n</yap-show>"
        doc = transform(md)
        assert len(doc.blocks) >= 1
        all_html = " ".join(getattr(b, "html", "") for b in doc.blocks if hasattr(b, "html"))
        assert "E=mc^2" in all_html or "math-inline" in all_html

    def test_multiline_yap_show_with_list(self):
        """Multi-line yap-show with list items."""
        md = "<yap-show>\n- Item A\n- Item B\n</yap-show>"
        doc = transform(md)
        list_blocks = [b for b in doc.blocks if b.type == "list"]
        assert len(list_blocks) == 1
        # List items should have no audio
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
        all_html = " ".join(getattr(b, "html", "") for b in doc.blocks if hasattr(b, "html"))
        assert "spoken only" not in all_html

    def test_multiline_yap_show_between_content(self):
        """Multi-line yap-show between regular content blocks."""
        md = "# Title\n\n<yap-show>\n© 2024 License info.\n</yap-show>\n\nRegular paragraph."
        doc = transform(md)
        audio = doc.get_audio_blocks()
        # Audio should have title + paragraph, NOT the show content
        assert any("Title" in t for t in audio)
        assert any("Regular paragraph" in t for t in audio)
        assert not any("License" in t for t in audio)


# === 4. HTML_INLINE SANITIZATION ===


class TestHtmlInlineSanitization:
    """Raw html_inline nodes should be escaped/dropped, not passed through."""

    def test_raw_html_not_in_block_html(self):
        """Raw HTML tags in markdown should not appear verbatim in block.html."""
        doc = transform("Text with <img src=x onerror=alert(1)> here.")
        block = doc.blocks[0]
        assert "onerror" not in block.html

    def test_raw_script_tag_not_in_html(self):
        """Script tags in markdown should not pass through."""
        doc = transform("Text <script>alert(1)</script> end.")
        block = doc.blocks[0]
        assert "<script>" not in block.html

    def test_yap_tags_still_work(self):
        """Yap tags (our html_inline) should still function normally."""
        doc = transform("Text <yap-show>[1]</yap-show> more.")
        block = doc.blocks[0]
        assert "[1]" in block.html

    def test_raw_html_not_in_ast(self):
        """Raw HTML should not appear in AST nodes."""
        doc = transform("Text <img src=x onerror=alert(1)> here.")
        block = doc.blocks[0]
        # AST should only contain known node types
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
                "footnote_ref",
            ), f"Unexpected AST node type: {node.type}"


# === 5. IMAGE CAPTION AST ROUNDTRIP ===


class TestImageCaptionAstRoundtrip:
    """Image captions go through split_with_spans — verify chunk ASTs roundtrip."""

    def test_single_chunk_caption_roundtrip(self):
        """Single-chunk caption: chunk.ast roundtrips to caption HTML."""
        doc = transform("![alt](img.png)<yap-cap>Caption with **bold**</yap-cap>")
        block = doc.blocks[0]
        assert isinstance(block, ImageBlock)
        assert len(block.audio_chunks) == 1
        chunk = block.audio_chunks[0]
        # For single-chunk images, caption_html is None (frontend uses caption field)
        # but the chunk AST should still roundtrip to the caption's HTML
        rendered = render_ast_to_html(chunk.ast)
        assert "<strong>bold</strong>" in rendered
        assert "Caption with" in rendered

    def test_multi_chunk_caption_roundtrip(self):
        """Multi-chunk caption: reconstructed HTML matches caption_html."""
        doc = transform(
            "![alt](img.png)<yap-cap>First sentence of the caption here. "
            "Second sentence with *italic* formatting here too.</yap-cap>",
            max_block_chars=40,
        )
        block = doc.blocks[0]
        assert isinstance(block, ImageBlock)
        assert len(block.audio_chunks) > 1, "Caption should split into multiple chunks"
        parts = []
        for chunk in block.audio_chunks:
            chunk_html = render_ast_to_html(chunk.ast)
            parts.append(f'<span data-audio-idx="{chunk.audio_block_idx}">{chunk_html}</span>')
        reconstructed = " ".join(parts)
        assert reconstructed == block.caption_html

    def test_alt_text_fallback_roundtrip(self):
        """Image with alt text (no caption): chunk.ast roundtrips to alt text."""
        doc = transform("![A descriptive alt text](img.png)")
        block = doc.blocks[0]
        assert isinstance(block, ImageBlock)
        assert len(block.audio_chunks) == 1
        chunk = block.audio_chunks[0]
        assert render_ast_to_html(chunk.ast) == "A descriptive alt text"

    def test_caption_with_math_roundtrip(self):
        """Caption with inline math: chunk AST includes MathInlineContent."""
        doc = transform(r"![alt](img.png)<yap-cap>Shows $\alpha$ decay</yap-cap>")
        block = doc.blocks[0]
        assert isinstance(block, ImageBlock)
        chunk = block.audio_chunks[0]
        rendered = render_ast_to_html(chunk.ast)
        assert "math-inline" in rendered
        assert r"\alpha" in rendered
        assert "Shows" in rendered


# === 6. YAP-SHOW EDGE CASES ===


class TestYapShowEdgeCases:
    """Edge cases for multi-line yap-show/yap-speak handling."""

    def test_unclosed_yap_show_still_renders(self):
        """Unclosed <yap-show> at end of document includes content (no audio)."""
        md = "# Title\n\n<yap-show>\nUnclosed copyright notice."
        doc = transform(md)
        # Content should appear somewhere despite missing close tag
        all_html = " ".join(getattr(b, "html", "") for b in doc.blocks if hasattr(b, "html"))
        assert "copyright notice" in all_html
        # And should have no audio (display-only)
        for block in doc.blocks:
            if hasattr(block, "html") and "copyright" in getattr(block, "html", ""):
                assert len(block.audio_chunks) == 0

    def test_yap_show_with_nested_blockquote(self):
        """yap-show containing a blockquote strips audio from nested blocks."""
        md = "<yap-show>\n> Quoted attribution text.\n</yap-show>"
        doc = transform(md)
        bq_blocks = [b for b in doc.blocks if isinstance(b, BlockquoteBlock)]
        assert len(bq_blocks) == 1
        bq = bq_blocks[0]
        # Blockquote itself has no audio
        assert len(bq.audio_chunks) == 0
        # Nested paragraph also has no audio
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

    def test_non_yap_html_block_silently_dropped(self):
        """Raw HTML blocks (not yap tags) are silently dropped."""
        md = "# Title\n\n<div class='custom'>Some HTML</div>\n\nParagraph."
        doc = transform(md)
        all_html = " ".join(getattr(b, "html", "") for b in doc.blocks if hasattr(b, "html"))
        assert "custom" not in all_html
        assert "Title" in all_html
        assert "Paragraph" in all_html

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
        all_text = " ".join(getattr(b, "html", "") for b in doc.blocks if hasattr(b, "html"))
        assert "Spoken paragraph" not in all_text
        assert "Title" in all_text
        assert "Visible" in all_text

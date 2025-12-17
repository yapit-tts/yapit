"""Tests for markdown parsing and transformation."""

import json

from yapit.gateway.processors.markdown import (
    parse_markdown,
    transform_to_document,
)
from yapit.gateway.processors.markdown.models import (
    BlockquoteBlock,
    CodeBlock,
    HeadingBlock,
    ListBlock,
    MathBlock,
    ParagraphBlock,
    StructuredDocument,
    TableBlock,
    ThematicBreak,
)


class TestParseMarkdown:
    """Test the markdown parsing wrapper."""

    def test_parse_simple_text(self):
        """Parse simple paragraph text."""
        ast = parse_markdown("Hello world")
        assert ast is not None
        assert ast.type == "root"
        assert len(ast.children) == 1
        assert ast.children[0].type == "paragraph"

    def test_parse_heading(self):
        """Parse heading syntax."""
        ast = parse_markdown("# Title\n\nSome text")
        assert len(ast.children) == 2
        assert ast.children[0].type == "heading"
        assert ast.children[0].tag == "h1"

    def test_parse_code_block(self):
        """Parse fenced code blocks."""
        ast = parse_markdown("```python\nprint('hello')\n```")
        assert len(ast.children) == 1
        assert ast.children[0].type == "fence"
        assert ast.children[0].info == "python"

    def test_parse_table(self):
        """Parse GFM tables."""
        md = "| A | B |\n|---|---|\n| 1 | 2 |"
        ast = parse_markdown(md)
        assert len(ast.children) == 1
        assert ast.children[0].type == "table"

    def test_parse_math_block(self):
        """Parse display math ($$...$$)."""
        ast = parse_markdown("$$\nx = y + z\n$$")
        assert len(ast.children) == 1
        assert ast.children[0].type == "math_block"


class TestTransformToDocument:
    """Test AST to StructuredDocument transformation."""

    def test_transform_paragraph(self):
        """Transform simple paragraph."""
        ast = parse_markdown("Hello world")
        doc = transform_to_document(ast)

        assert isinstance(doc, StructuredDocument)
        assert len(doc.blocks) == 1
        assert isinstance(doc.blocks[0], ParagraphBlock)
        assert doc.blocks[0].plain_text == "Hello world"
        assert doc.blocks[0].html == "Hello world"
        assert doc.blocks[0].audio_block_idx == 0

    def test_transform_heading(self):
        """Transform heading with level."""
        ast = parse_markdown("## Section Title")
        doc = transform_to_document(ast)

        assert len(doc.blocks) == 1
        block = doc.blocks[0]
        assert isinstance(block, HeadingBlock)
        assert block.level == 2
        assert block.plain_text == "Section Title"
        assert block.audio_block_idx == 0

    def test_transform_code_block(self):
        """Transform code block - no audio."""
        ast = parse_markdown("```python\nprint('hi')\n```")
        doc = transform_to_document(ast)

        assert len(doc.blocks) == 1
        block = doc.blocks[0]
        assert isinstance(block, CodeBlock)
        assert block.language == "python"
        assert block.content == "print('hi')"
        assert block.audio_block_idx is None

    def test_transform_math_block(self):
        """Transform math block - no audio."""
        ast = parse_markdown("$$\nE = mc^2\n$$")
        doc = transform_to_document(ast)

        assert len(doc.blocks) == 1
        block = doc.blocks[0]
        assert isinstance(block, MathBlock)
        assert "E = mc^2" in block.content
        assert block.audio_block_idx is None

    def test_transform_table(self):
        """Transform table - no audio."""
        md = "| Header |\n|--------|\n| Cell |"
        ast = parse_markdown(md)
        doc = transform_to_document(ast)

        assert len(doc.blocks) == 1
        block = doc.blocks[0]
        assert isinstance(block, TableBlock)
        assert block.headers == ["Header"]
        assert block.rows == [["Cell"]]
        assert block.audio_block_idx is None

    def test_transform_thematic_break(self):
        """Transform horizontal rule - no audio."""
        ast = parse_markdown("---")
        doc = transform_to_document(ast)

        assert len(doc.blocks) == 1
        assert isinstance(doc.blocks[0], ThematicBreak)
        assert doc.blocks[0].audio_block_idx is None

    def test_transform_unordered_list(self):
        """Transform bullet list."""
        ast = parse_markdown("- Item 1\n- Item 2")
        doc = transform_to_document(ast)

        assert len(doc.blocks) == 1
        block = doc.blocks[0]
        assert isinstance(block, ListBlock)
        assert block.ordered is False
        assert len(block.items) == 2
        assert block.items[0].plain_text == "Item 1"
        assert block.audio_block_idx == 0

    def test_transform_ordered_list(self):
        """Transform numbered list."""
        ast = parse_markdown("1. First\n2. Second")
        doc = transform_to_document(ast)

        block = doc.blocks[0]
        assert isinstance(block, ListBlock)
        assert block.ordered is True
        assert len(block.items) == 2

    def test_transform_blockquote(self):
        """Transform blockquote with nested content."""
        ast = parse_markdown("> A quote\n> with multiple lines")
        doc = transform_to_document(ast)

        assert len(doc.blocks) == 1
        block = doc.blocks[0]
        assert isinstance(block, BlockquoteBlock)
        # Blockquote has nested paragraph (idx 0), then blockquote itself (idx 1)
        assert block.audio_block_idx == 1
        assert len(block.blocks) == 1
        assert block.blocks[0].audio_block_idx == 0


class TestInlineFormatting:
    """Test inline formatting preservation."""

    def test_strong_formatting(self):
        """Bold text preserved in HTML and AST."""
        ast = parse_markdown("This is **bold** text")
        doc = transform_to_document(ast)

        block = doc.blocks[0]
        assert "<strong>bold</strong>" in block.html
        assert block.plain_text == "This is bold text"

        # Check AST
        ast_types = [c.type for c in block.ast]
        assert "text" in ast_types
        assert "strong" in ast_types

    def test_emphasis_formatting(self):
        """Italic text preserved in HTML and AST."""
        ast = parse_markdown("This is *italic* text")
        doc = transform_to_document(ast)

        block = doc.blocks[0]
        assert "<em>italic</em>" in block.html
        assert block.plain_text == "This is italic text"

    def test_inline_code(self):
        """Inline code preserved."""
        ast = parse_markdown("Use `print()` function")
        doc = transform_to_document(ast)

        block = doc.blocks[0]
        assert "<code>print()</code>" in block.html
        assert "print()" in block.plain_text

    def test_link_formatting(self):
        """Links preserved in HTML."""
        ast = parse_markdown("Visit [Google](https://google.com)")
        doc = transform_to_document(ast)

        block = doc.blocks[0]
        assert 'href="https://google.com"' in block.html


class TestParagraphSplitting:
    """Test large paragraph splitting at sentence boundaries."""

    def test_no_split_for_small_paragraph(self):
        """Small paragraphs are not split."""
        text = "This is a short paragraph."
        ast = parse_markdown(text)
        doc = transform_to_document(ast, max_block_chars=1000)

        assert len(doc.blocks) == 1

    def test_split_large_paragraph(self):
        """Large paragraphs are split at sentence boundaries."""
        # Create a paragraph > 100 chars with multiple sentences
        text = "This is sentence one. This is sentence two. This is sentence three. This is sentence four. This is sentence five."
        ast = parse_markdown(text)
        doc = transform_to_document(ast, max_block_chars=50)

        # Should be split into multiple blocks
        assert len(doc.blocks) > 1
        # Each block should have its own audio index
        audio_indices = [b.audio_block_idx for b in doc.blocks]
        assert audio_indices == list(range(len(doc.blocks)))

    def test_split_respects_sentence_boundaries(self):
        """Splits prefer sentence boundaries over hard cuts."""
        text = "First sentence here. Second sentence here. Third sentence here."
        ast = parse_markdown(text)
        doc = transform_to_document(ast, max_block_chars=50)

        # Check that blocks end at sentence boundaries (with period)
        for block in doc.blocks:
            assert block.plain_text.endswith(".") or block.plain_text.endswith(".")

    def test_split_paragraphs_share_visual_group_id(self):
        """Split paragraph blocks share the same visual_group_id."""
        text = "Sentence one here. Sentence two here. Sentence three here. Sentence four here."
        ast = parse_markdown(text)
        doc = transform_to_document(ast, max_block_chars=50)

        # Should have multiple blocks from the same paragraph
        assert len(doc.blocks) > 1
        # All should share the same visual_group_id
        group_ids = [b.visual_group_id for b in doc.blocks]
        assert all(g == group_ids[0] for g in group_ids)
        assert group_ids[0] is not None

    def test_unsplit_paragraph_has_no_visual_group_id(self):
        """Unsplit paragraphs have visual_group_id = None."""
        text = "Short paragraph."
        ast = parse_markdown(text)
        doc = transform_to_document(ast, max_block_chars=1000)

        assert len(doc.blocks) == 1
        assert doc.blocks[0].visual_group_id is None

    def test_split_preserves_bold_formatting(self):
        """Bold formatting is preserved when paragraph is split."""
        text = "This paper presents **Yapit**, an open-source platform. It provides text-to-speech capabilities."
        ast = parse_markdown(text)
        doc = transform_to_document(ast, max_block_chars=60)

        # Should split into 2 blocks
        assert len(doc.blocks) == 2

        # First block should have bold formatting in HTML
        assert "<strong>Yapit</strong>" in doc.blocks[0].html

        # First block AST should contain strong node
        ast_types = [node.type for node in doc.blocks[0].ast]
        assert "strong" in ast_types

    def test_split_preserves_italic_formatting(self):
        """Italic formatting is preserved when paragraph is split."""
        text = "The *important* feature is speed. Another sentence here to force a split."
        ast = parse_markdown(text)
        doc = transform_to_document(ast, max_block_chars=40)

        # Should split
        assert len(doc.blocks) >= 2

        # First block should have italic formatting
        assert "<em>important</em>" in doc.blocks[0].html

    def test_split_preserves_nested_formatting(self):
        """Nested formatting (bold inside italic) is preserved."""
        text = "Here is *italic with **bold** inside* text. More text here to split."
        ast = parse_markdown(text)
        doc = transform_to_document(ast, max_block_chars=50)

        # First block should have nested formatting
        assert "<em>" in doc.blocks[0].html
        assert "<strong>" in doc.blocks[0].html


class TestAudioBlockIndexing:
    """Test audio block index assignment."""

    def test_sequential_audio_indices(self):
        """Audio indices are assigned sequentially to prose blocks."""
        md = "# Heading\n\nParagraph one.\n\nParagraph two."
        ast = parse_markdown(md)
        doc = transform_to_document(ast)

        assert doc.blocks[0].audio_block_idx == 0  # Heading
        assert doc.blocks[1].audio_block_idx == 1  # Para 1
        assert doc.blocks[2].audio_block_idx == 2  # Para 2

    def test_code_blocks_skip_audio_index(self):
        """Code blocks don't consume audio indices."""
        md = "# Title\n\n```python\ncode\n```\n\nAfter code."
        ast = parse_markdown(md)
        doc = transform_to_document(ast)

        assert doc.blocks[0].audio_block_idx == 0  # Heading
        assert doc.blocks[1].audio_block_idx is None  # Code
        assert doc.blocks[2].audio_block_idx == 1  # Paragraph (not 2!)

    def test_get_audio_blocks(self):
        """get_audio_blocks() returns only prose text."""
        md = "# Title\n\n```python\ncode\n```\n\nSome text."
        ast = parse_markdown(md)
        doc = transform_to_document(ast)

        audio_blocks = doc.get_audio_blocks()
        assert len(audio_blocks) == 2
        assert audio_blocks[0] == "Title"
        assert audio_blocks[1] == "Some text."


class TestJsonSerialization:
    """Test JSON serialization of StructuredDocument."""

    def test_serialize_to_json(self):
        """Document serializes to valid JSON."""
        md = "# Test\n\nParagraph with **bold**.\n\n```py\ncode\n```"
        ast = parse_markdown(md)
        doc = transform_to_document(ast)

        json_str = doc.model_dump_json()
        parsed = json.loads(json_str)

        assert parsed["version"] == "1.0"
        assert len(parsed["blocks"]) == 3
        assert parsed["blocks"][0]["type"] == "heading"
        assert parsed["blocks"][1]["type"] == "paragraph"
        assert parsed["blocks"][2]["type"] == "code"

    def test_round_trip_serialization(self):
        """Document survives JSON round-trip."""
        md = "# Title\n\n- Item 1\n- Item 2"
        ast = parse_markdown(md)
        original = transform_to_document(ast)

        json_str = original.model_dump_json()
        restored = StructuredDocument.model_validate_json(json_str)

        assert len(restored.blocks) == len(original.blocks)
        assert restored.blocks[0].type == "heading"
        assert restored.blocks[1].type == "list"


class TestComplexDocument:
    """Test complex document with multiple element types."""

    def test_mixed_content_document(self):
        """Full document with various markdown elements."""
        md = """# Introduction

This is the **introduction** paragraph.

## Features

- Fast parsing
- Clean output
- *Flexible* design

Here's some code:

```python
def hello():
    print("Hello")
```

---

> Important note here.

| Name | Value |
|------|-------|
| A    | 1     |

$$
f(x) = x^2
$$

Final thoughts.
"""
        ast = parse_markdown(md)
        doc = transform_to_document(ast)

        # Verify we got all block types
        types = [b.type for b in doc.blocks]
        assert "heading" in types
        assert "paragraph" in types
        assert "list" in types
        assert "code" in types
        assert "hr" in types
        assert "blockquote" in types
        assert "table" in types
        assert "math" in types

        # Verify audio indices are correct for prose blocks
        audio_blocks = doc.get_audio_blocks()
        # Should include: 2 headings, 2 paragraphs, 1 list, 1 blockquote = 6
        assert len(audio_blocks) >= 5

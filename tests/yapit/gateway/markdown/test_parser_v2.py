"""Comprehensive tests for the parser rewrite.

These tests define the expected behavior for the v2 parser with:
- Unified AudioChunk model
- yap-show / yap-speak symmetric tags
- yap-cap for image captions
- Universal max_block_chars splitting

Tests are organized by feature area. Many will FAIL against the current
implementation — they define the target spec for the rewrite.
"""

from yapit.gateway.markdown import parse_markdown, transform_to_document
from yapit.gateway.markdown.models import (
    ImageBlock,
    ListBlock,
    MathBlock,
)

# === TEST DEFAULTS (production values come from env vars) ===

DEFAULT_MAX_BLOCK_CHARS = 250
DEFAULT_SOFT_LIMIT_MULT = 1.3
DEFAULT_MIN_CHUNK_SIZE = 40


def transform(ast, **kwargs):
    """Helper that provides test defaults for transform_to_document."""
    return transform_to_document(
        ast,
        max_block_chars=kwargs.get("max_block_chars", DEFAULT_MAX_BLOCK_CHARS),
        soft_limit_mult=kwargs.get("soft_limit_mult", DEFAULT_SOFT_LIMIT_MULT),
        min_chunk_size=kwargs.get("min_chunk_size", DEFAULT_MIN_CHUNK_SIZE),
    )


# === HELPER FUNCTIONS ===


def get_display_and_tts(markdown: str, **kwargs) -> tuple[str, str]:
    """Transform markdown and return (first block's html, first block's TTS text)."""
    ast = parse_markdown(markdown)
    doc = transform(ast, **kwargs)
    block = doc.blocks[0]
    html = getattr(block, "html", "") or ""
    # For unified model: concatenate all audio chunk texts
    if hasattr(block, "audio_chunks") and block.audio_chunks:
        tts = " ".join(chunk.text for chunk in block.audio_chunks)
    else:
        tts = getattr(block, "plain_text", "") or ""
    return html, tts


def get_audio_texts(markdown: str, **kwargs) -> list[str]:
    """Get all TTS texts from document in order."""
    ast = parse_markdown(markdown)
    doc = transform(ast, **kwargs)
    return doc.get_audio_blocks()


def get_all_audio_chunks(markdown: str, **kwargs):
    """Get all audio chunks from all blocks."""
    ast = parse_markdown(markdown)
    doc = transform(ast, **kwargs)
    chunks = []
    for block in doc.blocks:
        if hasattr(block, "audio_chunks"):
            chunks.extend(block.audio_chunks)
        elif hasattr(block, "items"):  # ListBlock
            for item in block.items:
                if hasattr(item, "audio_chunks"):
                    chunks.extend(item.audio_chunks)
    return chunks


# === 1. MATH BEHAVIOR ===


class TestMathAlwaysSilent:
    """Math contributes nothing to TTS on its own."""

    def test_inline_math_no_tts(self):
        """Inline math without yap-speak produces no TTS."""
        _, tts = get_display_and_tts(r"Value is $x^2$ here.")
        # Math is silent, so TTS should be "Value is  here." (or normalized)
        assert "x^2" not in tts
        assert "Value is" in tts
        assert "here" in tts

    def test_inline_math_displayed(self):
        """Inline math is displayed even without yap-speak."""
        html, _ = get_display_and_tts(r"Value is $x^2$ here.")
        assert "x^2" in html or "math-inline" in html

    def test_display_math_no_tts(self):
        """Display math without yap-speak produces no TTS."""
        md = "$$E = mc^2$$"
        ast = parse_markdown(md)
        doc = transform(ast)
        block = doc.blocks[0]
        assert isinstance(block, MathBlock)
        # No audio if no yap-speak
        assert len(block.audio_chunks) == 0

    def test_paragraph_only_math_no_audio(self):
        """Paragraph containing only math (no yap-speak) has no audio."""
        audio = get_audio_texts(r"$\alpha$")
        assert audio == [] or audio == [""]


# === 2. YAP-SPEAK TAG ===


class TestYapSpeak:
    """yap-speak content goes to TTS, not display."""

    def test_standalone_yap_speak(self):
        """Standalone yap-speak: spoken but not displayed."""
        html, tts = get_display_and_tts("Text <yap-speak>spoken</yap-speak> more.")
        assert "spoken" not in html
        assert "spoken" in tts
        assert "Text" in html and "more" in html
        assert "Text" in tts and "more" in tts

    def test_yap_speak_after_math(self):
        """yap-speak after math provides pronunciation."""
        html, tts = get_display_and_tts(r"The $\alpha$<yap-speak>alpha</yap-speak> value.")
        # Display: shows math
        assert "alpha" in html or "math-inline" in html
        # TTS: uses yap-speak content
        assert "alpha" in tts
        assert "The" in tts and "value" in tts

    def test_multiple_yap_speak_in_paragraph(self):
        """Multiple yap-speak tags accumulate in TTS."""
        html, tts = get_display_and_tts(r"$\alpha$<yap-speak>alpha</yap-speak> and $\beta$<yap-speak>beta</yap-speak>")
        assert "alpha" in tts
        assert "beta" in tts
        assert "and" in tts

    def test_yap_speak_empty(self):
        """Empty yap-speak is valid (contributes nothing)."""
        html, tts = get_display_and_tts("Text <yap-speak></yap-speak> more.")
        assert "Text" in tts
        assert "more" in tts

    def test_yap_speak_with_formatting(self):
        """yap-speak can contain formatting (ignored for TTS, not displayed anyway)."""
        # The content inside yap-speak goes to TTS as plain text
        _, tts = get_display_and_tts("Say <yap-speak>**bold** words</yap-speak> now.")
        assert "bold" in tts or "words" in tts


# === 3. YAP-SHOW TAG ===


class TestYapShow:
    """yap-show content goes to display, not TTS."""

    def test_standalone_yap_show(self):
        """Standalone yap-show: displayed but not spoken."""
        html, tts = get_display_and_tts("Text <yap-show>[1, 2]</yap-show> more.")
        assert "[1, 2]" in html
        assert "[1, 2]" not in tts
        assert "Text" in tts and "more" in tts

    def test_yap_show_with_following_yap_speak(self):
        """yap-show followed by yap-speak: display X, speak Y."""
        html, tts = get_display_and_tts(
            "As <yap-show>(Smith et al.)</yap-show><yap-speak>Smith and colleagues</yap-speak> showed."
        )
        assert "(Smith et al.)" in html
        assert "Smith and colleagues" in tts
        assert "(Smith et al.)" not in tts

    def test_yap_show_creates_display_only_zone(self):
        """Content inside yap-show is excluded from TTS, including nested yap-speak."""
        html, tts = get_display_and_tts("<yap-show>visible <yap-speak>inner</yap-speak></yap-show>")
        # Display shows the visible content
        assert "visible" in html
        # TTS gets nothing from inside yap-show (inner yap-speak is suppressed)
        assert "inner" not in tts
        assert "visible" not in tts

    def test_yap_show_with_math_inside(self):
        """Math inside yap-show is displayed but not spoken."""
        html, tts = get_display_and_tts(r"<yap-show>see $\alpha$</yap-show>")
        # Display shows math
        assert "alpha" in html or "math-inline" in html
        # TTS is empty (or just whitespace)
        assert not tts.strip() or "alpha" not in tts

    def test_yap_show_with_links(self):
        """yap-show supports links inside."""
        html, tts = get_display_and_tts("Check <yap-show>[the docs](http://example.com)</yap-show> for details.")
        assert "the docs" in html or "example.com" in html
        assert "the docs" not in tts
        assert "Check" in tts and "details" in tts


# === 4. YAP-CAP TAG (IMAGE CAPTIONS) ===


class TestYapCap:
    """yap-cap provides caption for preceding image."""

    def test_image_with_caption(self):
        """Basic image caption extraction."""
        md = "![alt text](img.png)<yap-cap>Figure 1 caption</yap-cap>"
        ast = parse_markdown(md)
        doc = transform(ast)
        block = doc.blocks[0]
        assert isinstance(block, ImageBlock)
        assert block.caption == "Figure 1 caption"

    def test_caption_used_for_tts(self):
        """Caption is used for TTS (not alt text when caption present)."""
        md = "![alt](img.png)<yap-cap>The caption</yap-cap>"
        ast = parse_markdown(md)
        doc = transform(ast)
        audio = doc.get_audio_blocks()
        assert "The caption" in audio[0] if audio else False

    def test_caption_with_math_and_yap_speak(self):
        """Caption with math uses yap-speak for TTS."""
        md = r"![](img.png)<yap-cap>Shows $\beta$<yap-speak>beta</yap-speak> values</yap-cap>"
        ast = parse_markdown(md)
        doc = transform(ast)
        block = doc.blocks[0]
        assert isinstance(block, ImageBlock)
        # Display caption includes math
        assert r"$\beta$" in block.caption or "beta" in block.caption
        # TTS uses yap-speak
        audio = doc.get_audio_blocks()
        assert audio and "beta" in audio[0]

    def test_caption_with_yap_show(self):
        """Caption can contain yap-show for display-only refs."""
        md = "![](img.png)<yap-cap>Result <yap-show>[1]</yap-show> analysis</yap-cap>"
        ast = parse_markdown(md)
        doc = transform(ast)
        block = doc.blocks[0]
        # Display caption includes [1]
        assert "[1]" in block.caption
        # TTS excludes [1]
        audio = doc.get_audio_blocks()
        assert audio and "[1]" not in audio[0]
        assert "Result" in audio[0] and "analysis" in audio[0]

    def test_caption_with_show_and_speak(self):
        """Caption with yap-show + yap-speak composition."""
        md = "![](img.png)<yap-cap>From <yap-show>(Smith, 2020)</yap-show><yap-speak>Smith</yap-speak></yap-cap>"
        ast = parse_markdown(md)
        doc = transform(ast)
        block = doc.blocks[0]
        # Display: "From (Smith, 2020)"
        assert "(Smith, 2020)" in block.caption
        # TTS: "From Smith"
        audio = doc.get_audio_blocks()
        assert audio and "Smith" in audio[0]
        assert "(Smith, 2020)" not in audio[0]


# === 5. TAG COMPOSITION ===


class TestTagComposition:
    """Complex combinations of yap tags."""

    def test_show_speak_adjacent(self):
        """Adjacent yap-show and yap-speak produce display/speak split."""
        html, tts = get_display_and_tts("<yap-show>DISPLAY</yap-show><yap-speak>SPEAK</yap-speak>")
        assert "DISPLAY" in html
        assert "DISPLAY" not in tts
        assert "SPEAK" in tts
        assert "SPEAK" not in html

    def test_math_show_speak_chain(self):
        """Complex: math followed by show+speak."""
        md = r"$x$<yap-show>=$y$</yap-show><yap-speak>x equals y</yap-speak>"
        html, tts = get_display_and_tts(md)
        # Display: x = y (as math)
        assert "=" in html or "y" in html
        # TTS: "x equals y"
        assert "x equals y" in tts

    def test_nested_in_caption(self):
        """Full nesting in caption: math + show + speak."""
        md = "![](img.png)<yap-cap>Fig 1: $\\alpha$<yap-speak>alpha</yap-speak> <yap-show>[1]</yap-show></yap-cap>"
        ast = parse_markdown(md)
        doc = transform(ast)
        block = doc.blocks[0]
        # Caption display includes math and [1]
        assert "[1]" in block.caption
        # TTS: "Fig 1: alpha" (no [1], math replaced)
        audio = doc.get_audio_blocks()
        assert audio
        assert "alpha" in audio[0]
        assert "[1]" not in audio[0]


# === 6. AUDIO CHUNK MODEL ===


class TestAudioChunkModel:
    """Blocks have audio_chunks list instead of single audio_block_idx."""

    def test_paragraph_has_audio_chunks(self):
        """ParagraphBlock has audio_chunks attribute."""
        ast = parse_markdown("Hello world")
        doc = transform(ast)
        block = doc.blocks[0]
        assert hasattr(block, "audio_chunks")
        assert len(block.audio_chunks) == 1
        assert block.audio_chunks[0].text == "Hello world"

    def test_short_paragraph_single_chunk(self):
        """Short paragraph produces single audio chunk."""
        ast = parse_markdown("Short text.")
        doc = transform(ast, max_block_chars=1000)
        block = doc.blocks[0]
        assert len(block.audio_chunks) == 1

    def test_list_items_have_audio_chunks(self):
        """ListItem has audio_chunks attribute."""
        ast = parse_markdown("- Item one\n- Item two")
        doc = transform(ast)
        block = doc.blocks[0]
        assert isinstance(block, ListBlock)
        assert hasattr(block.items[0], "audio_chunks")
        assert len(block.items[0].audio_chunks) >= 1

    def test_image_has_audio_chunks(self):
        """ImageBlock has audio_chunks for caption."""
        md = "![alt](img.png)<yap-cap>Caption text</yap-cap>"
        ast = parse_markdown(md)
        doc = transform(ast)
        block = doc.blocks[0]
        assert isinstance(block, ImageBlock)
        assert hasattr(block, "audio_chunks")
        assert len(block.audio_chunks) == 1
        assert "Caption" in block.audio_chunks[0].text


# === 7. SPLITTING (max_block_chars) ===


class TestUniversalSplitting:
    """All audio content respects max_block_chars."""

    def test_paragraph_splits_into_chunks(self):
        """Long paragraph splits into multiple audio chunks."""
        text = "First sentence here. Second sentence here. Third sentence here."
        ast = parse_markdown(text)
        doc = transform(ast, max_block_chars=30)
        block = doc.blocks[0]
        assert len(block.audio_chunks) > 1
        # Each chunk should be under limit (approximately)
        for chunk in block.audio_chunks:
            assert len(chunk.text) <= 50  # Allow some flexibility

    def test_split_paragraph_single_display_block(self):
        """Split paragraph is still ONE display block (not multiple)."""
        text = "First sentence here. Second sentence here. Third sentence here."
        ast = parse_markdown(text)
        doc = transform(ast, max_block_chars=30)
        # Only one block in the list
        para_blocks = [b for b in doc.blocks if b.type == "paragraph"]
        assert len(para_blocks) == 1

    def test_split_paragraph_html_has_span_wrappers(self):
        """Split paragraph HTML contains span wrappers with audio indices."""
        text = "First sentence here. Second sentence here. Third sentence here."
        ast = parse_markdown(text)
        doc = transform(ast, max_block_chars=30)
        block = doc.blocks[0]
        # HTML should have data-audio-idx spans
        assert "data-audio-idx" in block.html or "data-audio-block-idx" in block.html

    def test_list_item_splits(self):
        """Long list item splits into multiple audio chunks."""
        md = "- This is a very long list item. It contains multiple sentences. And should split."
        ast = parse_markdown(md)
        doc = transform(ast, max_block_chars=30)
        block = doc.blocks[0]
        assert isinstance(block, ListBlock)
        item = block.items[0]
        assert len(item.audio_chunks) > 1

    def test_image_caption_splits(self):
        """Long image caption splits into multiple audio chunks."""
        md = "![](img.png)<yap-cap>This is a very long caption. It has multiple sentences. And should split properly.</yap-cap>"
        ast = parse_markdown(md)
        doc = transform(ast, max_block_chars=30)
        block = doc.blocks[0]
        assert isinstance(block, ImageBlock)
        assert len(block.audio_chunks) > 1

    def test_audio_indices_sequential(self):
        """Audio chunk indices are assigned sequentially across blocks."""
        md = "First para. Second sentence.\n\n- List item one.\n- List item two."
        chunks = get_all_audio_chunks(md, max_block_chars=20)
        indices = [c.audio_block_idx for c in chunks]
        # Should be sequential: 0, 1, 2, ...
        assert indices == list(range(len(indices)))

    def test_split_preserves_formatting(self):
        """Splitting preserves bold/italic formatting in each chunk."""
        text = "This has **bold text** in it. And more **bold** in second sentence."
        ast = parse_markdown(text)
        doc = transform(ast, max_block_chars=40)
        block = doc.blocks[0]
        # If split, check that HTML still has strong tags
        if len(block.audio_chunks) > 1:
            assert "<strong>" in block.html


# === 8. EDGE CASES & MALFORMED INPUT ===


class TestEdgeCases:
    """Graceful handling of edge cases and malformed input."""

    def test_unclosed_yap_speak(self):
        """Unclosed yap-speak is treated as text."""
        html, tts = get_display_and_tts("Text <yap-speak>unclosed")
        # Should not crash
        assert "Text" in tts or "Text" in html

    def test_unclosed_yap_show(self):
        """Unclosed yap-show is treated as text."""
        html, tts = get_display_and_tts("Text <yap-show>unclosed")
        # Should not crash
        assert "Text" in tts or "Text" in html

    def test_unclosed_yap_cap(self):
        """Unclosed yap-cap is treated as text."""
        md = "![](img.png)<yap-cap>unclosed caption"
        ast = parse_markdown(md)
        doc = transform(ast)
        # Should not crash
        assert len(doc.blocks) >= 1

    def test_nested_same_tags(self):
        """Nested same tags treated as text (undefined behavior)."""
        html, tts = get_display_and_tts("<yap-show><yap-show>x</yap-show></yap-show>")
        # Should not crash, exact behavior undefined
        assert True  # Just verify no exception

    def test_empty_tags(self):
        """Empty tags are valid."""
        html, tts = get_display_and_tts("<yap-show></yap-show><yap-speak></yap-speak>")
        # Should produce empty or minimal output
        assert True  # No crash

    def test_tags_with_only_whitespace(self):
        """Tags with only whitespace inside."""
        html, tts = get_display_and_tts("<yap-show>   </yap-show>")
        # Whitespace in display
        assert True  # No crash

    def test_double_spaces_normalized(self):
        """Double spaces from tag removal are normalized (if implemented)."""
        _, tts = get_display_and_tts("Text <yap-show>X</yap-show> more.")
        # Either "Text  more" or "Text more" is acceptable
        assert "Text" in tts and "more" in tts


# === 9. DISPLAY MATH WITH YAP-SPEAK ===


class TestDisplayMath:
    """Display math ($$...$$) with yap-speak."""

    def test_display_math_with_yap_speak_next_line(self):
        """Display math followed by yap-speak on next line."""
        md = "$$E = mc^2$$\n<yap-speak>E equals m c squared</yap-speak>"
        ast = parse_markdown(md)
        doc = transform(ast)
        # Should have math block with TTS
        math_blocks = [b for b in doc.blocks if b.type == "math"]
        assert len(math_blocks) == 1
        audio = doc.get_audio_blocks()
        assert audio and "E equals" in audio[0]

    def test_display_math_with_blank_line_before_speak(self):
        """Blank line between math and yap-speak."""
        md = "$$E = mc^2$$\n\n<yap-speak>E equals m c squared</yap-speak>"
        ast = parse_markdown(md)
        doc = transform(ast)
        audio = doc.get_audio_blocks()
        assert audio and "E equals" in audio[0]

    def test_consecutive_display_math(self):
        """Multiple display math blocks each with yap-speak."""
        md = "$$eq1$$\n<yap-speak>equation one</yap-speak>\n\n$$eq2$$\n<yap-speak>equation two</yap-speak>"
        ast = parse_markdown(md)
        doc = transform(ast)
        audio = doc.get_audio_blocks()
        assert len(audio) == 2
        assert "equation one" in audio[0]
        assert "equation two" in audio[1]


# === 10. BASIC BLOCK TYPES (HAPPY PATHS) ===


class TestBasicBlockTypes:
    """Basic block types produce expected audio/display behavior."""

    def test_plain_paragraph_has_audio(self):
        """Plain paragraph without tags has audio."""
        ast = parse_markdown("Just a normal paragraph.")
        doc = transform(ast)
        audio = doc.get_audio_blocks()
        assert audio == ["Just a normal paragraph."]

    def test_heading_has_audio(self):
        """Headings have audio."""
        ast = parse_markdown("# My Heading")
        doc = transform(ast)
        audio = doc.get_audio_blocks()
        assert "My Heading" in audio

    def test_multiple_list_items_each_have_audio(self):
        """Each list item gets its own audio chunk."""
        ast = parse_markdown("- Item A\n- Item B\n- Item C")
        doc = transform(ast)
        audio = doc.get_audio_blocks()
        assert "Item A" in audio
        assert "Item B" in audio
        assert "Item C" in audio
        assert len(audio) == 3

    def test_code_block_no_audio(self):
        """Code blocks have no audio."""
        ast = parse_markdown("```python\nprint('hi')\n```")
        doc = transform(ast)
        audio = doc.get_audio_blocks()
        assert audio == []

    def test_table_no_audio(self):
        """Tables have no audio."""
        ast = parse_markdown("| A | B |\n|---|---|\n| 1 | 2 |")
        doc = transform(ast)
        audio = doc.get_audio_blocks()
        assert audio == []

    def test_hr_no_audio(self):
        """Horizontal rules have no audio."""
        ast = parse_markdown("---")
        doc = transform(ast)
        audio = doc.get_audio_blocks()
        assert audio == []

    def test_blockquote_nested_has_audio(self):
        """Blockquote's nested content has audio."""
        ast = parse_markdown("> This is quoted text.")
        doc = transform(ast)
        audio = doc.get_audio_blocks()
        assert "This is quoted text." in audio

    def test_image_with_alt_has_audio(self):
        """Image with alt text (no caption) uses alt for audio."""
        ast = parse_markdown("![A cute cat](cat.png)")
        doc = transform(ast)
        audio = doc.get_audio_blocks()
        assert "A cute cat" in audio

    def test_image_without_alt_no_audio(self):
        """Image without alt text has no audio."""
        ast = parse_markdown("![](img.png)")
        doc = transform(ast)
        audio = doc.get_audio_blocks()
        assert audio == []

    def test_bold_italic_in_paragraph(self):
        """Formatting in paragraph preserved in display, stripped for TTS."""
        html, tts = get_display_and_tts("This is **bold** and *italic* text.")
        assert "<strong>bold</strong>" in html
        assert "<em>italic</em>" in html
        assert tts == "This is bold and italic text."

    def test_link_in_paragraph(self):
        """Links preserved in display, text used for TTS."""
        html, tts = get_display_and_tts("Visit [Google](https://google.com) now.")
        assert "href=" in html
        assert tts == "Visit Google now."


# === 11. INTEGRATION: FULL DOCUMENT ===


class TestFullDocument:
    """Complete documents with multiple features."""

    def test_academic_paragraph(self):
        """Academic-style paragraph with math and citations."""
        md = (
            "As shown by <yap-show>(Smith, 2020)</yap-show><yap-speak>Smith</yap-speak>, "
            "the value $\\alpha$<yap-speak>alpha</yap-speak> is crucial "
            "<yap-show>[1, 2]</yap-show>."
        )
        html, tts = get_display_and_tts(md)
        # Display has citations
        assert "(Smith, 2020)" in html
        assert "[1, 2]" in html
        # TTS is clean
        assert "Smith" in tts
        assert "alpha" in tts
        assert "[1, 2]" not in tts
        assert "(Smith, 2020)" not in tts

    def test_figure_with_complex_caption(self):
        """Figure with caption containing math, refs, and formatting."""
        md = (
            "![Neural network diagram](img.png)<yap-cap>"
            "**Figure 1**: Architecture showing $\\lambda$<yap-speak>lambda</yap-speak> "
            "regularization <yap-show>(cf. [3])</yap-show>"
            "</yap-cap>"
        )
        ast = parse_markdown(md)
        doc = transform(ast)
        block = doc.blocks[0]
        assert isinstance(block, ImageBlock)
        # Caption has everything
        assert "Figure 1" in block.caption
        assert "[3]" in block.caption
        # TTS is clean
        audio = doc.get_audio_blocks()
        assert audio
        assert "lambda" in audio[0]
        assert "[3]" not in audio[0]

    def test_mixed_content_document(self):
        """Document with headings, paragraphs, math, images."""
        md = """# Introduction

The $\\alpha$<yap-speak>alpha</yap-speak> coefficient matters.

![Chart](fig.png)<yap-cap>Results for $\\beta$<yap-speak>beta</yap-speak></yap-cap>

## Methods

We used standard approaches <yap-show>[1-5]</yap-show>.
"""
        ast = parse_markdown(md)
        doc = transform(ast)
        audio = doc.get_audio_blocks()
        # Should have audio for: heading, paragraph, image caption, heading, paragraph
        assert len(audio) >= 4
        # Check math replacements worked
        full_audio = " ".join(audio)
        assert "alpha" in full_audio
        assert "beta" in full_audio
        assert "[1-5]" not in full_audio

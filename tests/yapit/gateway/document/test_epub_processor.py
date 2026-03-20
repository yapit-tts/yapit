"""Tests for EPUB extraction processor."""

import io
import shutil
import zipfile
from pathlib import Path

import pytest

from yapit.gateway.document.processors.epub import _clean_pandoc_output, _run_pandoc, extract_document_info

FIXTURES_DIR = Path("tests/fixtures/documents")

needs_pandoc = pytest.mark.skipif(not shutil.which("pandoc"), reason="pandoc not installed")


class TestExtractDocumentInfo:
    def test_extracts_title_from_opf(self):
        content = (FIXTURES_DIR / "test.epub").read_bytes()
        pages, title = extract_document_info(content)
        assert title == "Test EPUB Document"
        assert pages == 1

    def test_invalid_epub_raises(self):
        with pytest.raises(zipfile.BadZipFile):
            extract_document_info(b"not an epub")

    def test_empty_zip_raises(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w"):
            pass
        with pytest.raises(KeyError):
            extract_document_info(buf.getvalue())

    def test_valid_epub_without_title(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "META-INF/container.xml",
                '<?xml version="1.0"?>'
                '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">'
                '<rootfiles><rootfile full-path="content.opf"/></rootfiles></container>',
            )
            zf.writestr(
                "content.opf",
                '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf"><metadata/></package>',
            )
        pages, title = extract_document_info(buf.getvalue())
        assert pages == 1
        assert title is None


class TestCleanPandocOutput:
    def test_strips_empty_anchor_spans(self):
        md = 'Hello\n\n<span id="ch01.xhtml"></span>\n\nWorld'
        assert "<span" not in _clean_pandoc_output(md)
        assert "Hello" in _clean_pandoc_output(md)
        assert "World" in _clean_pandoc_output(md)

    def test_strips_pagebreak_spans(self):
        md = '<span id="p1" class="pagebreak" title="1"></span>Text here'
        assert _clean_pandoc_output(md) == "Text here"

    def test_strips_pagebreak_spans_with_aria(self):
        md = '<span id="p1" class="pagebreak" aria-label=" Page 1. " role="doc-pagebreak"></span>Text'
        assert _clean_pandoc_output(md) == "Text"

    def test_converts_smallcaps_to_uppercase(self):
        md = 'at 5:45 <span class="smallcaps">a.m.</span>, January 17'
        assert _clean_pandoc_output(md) == "at 5:45 A.M., January 17"

    def test_strips_decorative_wrappers_keeps_content(self):
        md = '<span class="figure_dingbat">![dingbat](img.jpg)</span>'
        assert _clean_pandoc_output(md) == "![dingbat](img.jpg)"

    def test_strips_aria_hidden_with_content(self):
        md = 'before<span aria-hidden="true">hidden</span>after'
        assert _clean_pandoc_output(md) == "beforeafter"

    def test_unwraps_remaining_spans(self):
        md = '<span class="sup">3</span> and <span class="abbr" title="AI">AI</span>'
        assert _clean_pandoc_output(md) == "3 and AI"

    def test_strips_svg_blocks(self):
        md = '![](cover.jpg)\n\n<svg xmlns="http://www.w3.org/2000/svg" viewbox="0 0 100 100"><image href="cover.jpg"></image></svg>\n\nText'
        result = _clean_pandoc_output(md)
        assert "<svg" not in result
        assert "![](cover.jpg)" in result
        assert "Text" in result

    def test_collapses_blank_lines(self):
        md = "Para one\n\n\n\n\nPara two"
        assert _clean_pandoc_output(md) == "Para one\n\nPara two"

    def test_combined_cleanup(self):
        md = (
            '<span id="ch01.xhtml"></span>\n\n'
            '<span class="pagebreak" title="1"></span>'
            "# Chapter One\n\n"
            'Text with <span class="smallcaps">a.m.</span> time.\n\n'
            '<span class="figure_dingbat"><img src="dingbat.jpg" role="presentation" /></span>'
        )
        result = _clean_pandoc_output(md)
        assert "<span" not in result
        assert "# Chapter One" in result
        assert "A.M." in result


@needs_pandoc
class TestRunPandoc:
    def test_returns_cleaned_markdown(self):
        content = (FIXTURES_DIR / "test.epub").read_bytes()
        markdown, images = _run_pandoc(content)
        assert len(markdown) > 0
        assert "<span" not in markdown

    def test_invalid_epub_raises(self):
        with pytest.raises(RuntimeError, match="EPUB extraction failed"):
            _run_pandoc(b"not an epub")


@needs_pandoc
class TestExtract:
    @pytest.mark.asyncio
    async def test_yields_single_page_result(self):
        from yapit.gateway.document.processors.epub import extract

        content = (FIXTURES_DIR / "test.epub").read_bytes()
        results = [r async for r in extract(content)]
        assert len(results) == 1
        assert results[0].page_idx == 0
        assert results[0].page is not None
        assert len(results[0].page.markdown) > 0

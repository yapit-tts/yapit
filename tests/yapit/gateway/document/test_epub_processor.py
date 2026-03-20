"""Tests for EPUB extraction processor."""

import io
import shutil
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from yapit.gateway.document.processors.epub import _run_pandoc, extract_document_info

FIXTURES_DIR = Path("tests/fixtures/documents")

needs_pandoc = pytest.mark.skipif(not shutil.which("pandoc"), reason="pandoc not installed")


class TestExtractDocumentInfo:
    def test_extracts_title_from_opf(self):
        content = (FIXTURES_DIR / "test.epub").read_bytes()
        pages, title = extract_document_info(content)
        assert title == "Test EPUB Document"
        assert pages == 1

    def test_invalid_epub_returns_defaults(self):
        pages, title = extract_document_info(b"not an epub")
        assert title is None
        assert pages == 1

    def test_empty_zip_returns_defaults(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w"):
            pass
        pages, title = extract_document_info(buf.getvalue())
        assert title is None
        assert pages == 1


@needs_pandoc
class TestRunPandoc:
    def test_returns_markdown_and_images(self):
        content = (FIXTURES_DIR / "test.epub").read_bytes()
        markdown, images = _run_pandoc(content)
        assert len(markdown) > 0
        assert isinstance(images, list)

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

    @pytest.mark.asyncio
    async def test_stores_images_when_storage_provided(self):
        from yapit.gateway.document.processors.epub import extract

        content = (FIXTURES_DIR / "test.epub").read_bytes()
        storage = AsyncMock()
        storage.store = AsyncMock(return_value="/images/test/0.jpg")

        results = [r async for r in extract(content, image_storage=storage, content_hash="abc")]
        # Test fixture has no images — verify no spurious storage calls
        assert storage.store.call_count == 0
        assert results[0].page.images == []

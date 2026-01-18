from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from yapit.gateway.document.markitdown import MarkitdownProcessor


class TestMarkitdownProcessor:
    """Test MarkitdownProcessor functionality."""

    @pytest.fixture
    def processor(self):
        """Create a markitdown processor instance."""
        mock_settings = Mock()
        return MarkitdownProcessor(settings=mock_settings)

    @pytest.fixture
    def mock_cache(self):
        """Create a mock extraction cache."""
        cache = AsyncMock()
        cache.store = AsyncMock()
        return cache

    @pytest.mark.asyncio
    async def test_extract_text_file(self, processor, mock_cache):
        """Test extracting from a text file."""
        test_content = b"This is a test text file.\nWith multiple lines."

        result = await processor._extract(
            content=test_content,
            content_type="text/plain",
            content_hash="test-hash",
            extraction_cache=mock_cache,
        )

        assert result.extraction_method == "markitdown"
        assert len(result.pages) == 1
        assert 0 in result.pages
        assert "This is a test text file" in result.pages[0].markdown

    @pytest.mark.asyncio
    async def test_extract_html_file(self, processor, mock_cache):
        """Test extracting from an HTML file."""
        fixtures_dir = Path("tests/fixtures/documents")
        with open(fixtures_dir / "test.html", "rb") as f:
            content = f.read()

        result = await processor._extract(
            content=content,
            content_type="text/html",
            content_hash="test-hash",
            extraction_cache=mock_cache,
        )

        assert result.extraction_method == "markitdown"
        assert len(result.pages) == 1
        assert 0 in result.pages
        # Markitdown should convert HTML to markdown
        assert "Test HTML Document" in result.pages[0].markdown

    @pytest.mark.asyncio
    async def test_extract_pdf_file(self, processor, mock_cache):
        """Test extracting from a PDF file."""
        fixtures_dir = Path("tests/fixtures/documents")
        with open(fixtures_dir / "minimal.pdf", "rb") as f:
            content = f.read()

        result = await processor._extract(
            content=content,
            content_type="application/pdf",
            content_hash="test-hash",
            extraction_cache=mock_cache,
        )

        assert result.extraction_method == "markitdown"
        assert len(result.pages) == 1
        assert 0 in result.pages
        # Should contain the PDF text
        assert "Test PDF Document" in result.pages[0].markdown

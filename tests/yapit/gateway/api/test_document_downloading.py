from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
from fastapi import HTTPException

from yapit.gateway.api.v1.documents import _download_document, _extract_document_info


class TestDownloadDocument:
    """Test _download_document function."""

    @pytest.mark.asyncio
    async def test_successful_download(self):
        """Test successful document download."""
        content = b"Test PDF content"

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/pdf"}
        mock_response.aiter_bytes = lambda chunk_size=8192: aiter([content])
        mock_response.raise_for_status = Mock()

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(return_value=mock_response)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result_content, content_type = await _download_document("https://example.com/test.pdf", 100 * 1024 * 1024)

            assert result_content == content
            assert content_type == "application/pdf"
            mock_client.head.assert_called_once()
            mock_client.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_download_size_limit_head(self):
        """Test file size limit enforcement via HEAD request."""
        mock_head_response = AsyncMock()
        mock_head_response.status_code = 200
        mock_head_response.headers = {"content-length": "200000000"}  # 200MB

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(return_value=mock_head_response)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with pytest.raises(HTTPException, match="File too large"):
                await _download_document("https://example.com/huge.pdf", 100 * 1024 * 1024)

            mock_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_download_size_limit_streaming(self):
        """Test file size limit enforcement during streaming."""
        # Simulate downloading more than the limit
        chunks = [b"x" * 8192 for _ in range(15000)]  # ~120MB

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/pdf"}
        mock_response.aiter_bytes = lambda chunk_size=8192: aiter(chunks)
        mock_response.raise_for_status = Mock()

        mock_head_response = AsyncMock()
        mock_head_response.status_code = 404  # HEAD fails, fallback to GET

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(return_value=mock_head_response)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with pytest.raises(HTTPException, match="File too large"):
                await _download_document("https://example.com/test.pdf", 100 * 1024 * 1024)

    @pytest.mark.asyncio
    async def test_download_http_error(self):
        """Test handling of HTTP errors."""
        mock_response = AsyncMock()
        mock_response.status_code = 404
        mock_response.raise_for_status = Mock(
            side_effect=httpx.HTTPStatusError("Not found", request=Mock(), response=mock_response)
        )

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(return_value=mock_response)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with pytest.raises(HTTPException) as exc_info:
                await _download_document("https://example.com/missing.pdf", 100 * 1024 * 1024)
            assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_download_network_error(self):
        """Test handling of network errors."""
        mock_client = AsyncMock()
        mock_client.head = AsyncMock(side_effect=httpx.RequestError("Connection failed"))

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with pytest.raises(HTTPException) as exc_info:
                await _download_document("https://example.com/test.pdf", 100 * 1024 * 1024)
            assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_download_no_content_type(self):
        """Test handling when content-type header is missing."""
        content = b"Some content"

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.headers = {}  # No content-type
        mock_response.aiter_bytes = lambda chunk_size=8192: aiter([content])
        mock_response.raise_for_status = Mock()

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(return_value=mock_response)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result_content, content_type = await _download_document("https://example.com/test", 100 * 1024 * 1024)

            assert result_content == content
            assert content_type == "application/octet-stream"


class TestExtractDocumentInfo:
    """Test _extract_document_info function."""

    def test_extract_pdf_info(self):
        """Test extracting info from PDF."""
        # Read actual test PDF
        with open("tests/fixtures/documents/minimal.pdf", "rb") as f:
            content = f.read()

        page_count, title = _extract_document_info(content, "application/pdf")

        assert page_count == 1
        assert title == "Test PDF Title"

    def test_extract_pdf_info_multipage(self):
        """Test extracting info from multi-page PDF."""
        with open("tests/fixtures/documents/multipage.pdf", "rb") as f:
            content = f.read()

        page_count, title = _extract_document_info(content, "application/pdf")

        assert page_count == 3
        assert title == "Multi-page Test PDF"

    def test_extract_html_info(self):
        """Test extracting info from HTML."""
        content = b"""<!DOCTYPE html>
        <html>
        <head>
            <title>Test HTML Title</title>
        </head>
        <body>Content</body>
        </html>"""

        page_count, title = _extract_document_info(content, "text/html")

        assert page_count == 1
        assert title == "Test HTML Title"

    def test_extract_html_no_title(self):
        """Test extracting info from HTML without title."""
        content = b"<html><body>No title here</body></html>"

        page_count, title = _extract_document_info(content, "text/html")

        assert page_count == 1
        assert title is None

    def test_extract_image_info(self):
        """Test extracting info from image."""
        # Read actual test image
        with open("tests/fixtures/documents/test.png", "rb") as f:
            content = f.read()

        page_count, title = _extract_document_info(content, "image/png")

        assert page_count == 1
        assert title is None

    def test_extract_unsupported_type(self):
        """Test handling of unsupported content types."""
        content = b"Some content"

        with pytest.raises(HTTPException, match="Unsupported content type for metadata extraction: application/json"):
            _extract_document_info(content, "application/json")


# Helper for async iteration
async def aiter(items):
    for item in items:
        yield item

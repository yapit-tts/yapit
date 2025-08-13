import base64
from unittest.mock import Mock, patch

import pytest

from yapit.gateway.processors.document.mistral import MistralOCRProcessor


class TestMistralOCRProcessor:
    """Test MistralOCRProcessor functionality."""

    @pytest.fixture
    def processor(self):
        """Create a Mistral OCR processor instance."""
        mock_settings = Mock()
        mock_settings.mistral_api_key = "test-api-key"

        # Mock the Mistral client
        with patch("yapit.gateway.processors.document.mistral.Mistral") as mock_mistral_class:
            processor = MistralOCRProcessor(slug="mistral-ocr", settings=mock_settings, model="test-model")
            processor._client = mock_mistral_class.return_value
            return processor

    @pytest.mark.asyncio
    async def test_extract_with_url(self, processor):
        """Test extraction with URL."""
        # Mock the OCR response
        mock_page = Mock()
        mock_page.index = 0
        mock_page.markdown = "Extracted text from image"
        mock_page.images = []  # No images in this example

        mock_response = Mock()
        mock_response.pages = [mock_page]

        processor._client.ocr.process = Mock(return_value=mock_response)

        result = await processor._extract(url="https://example.com/image.png", content_type="image/png")

        # Check the API was called correctly
        processor._client.ocr.process.assert_called_once()
        call_kwargs = processor._client.ocr.process.call_args.kwargs

        assert call_kwargs["model"] == "test-model"
        assert call_kwargs["document"]["type"] == "image_url"
        assert call_kwargs["document"]["image_url"] == "https://example.com/image.png"
        assert call_kwargs["include_image_base64"] is True
        assert call_kwargs["pages"] is None

        # Check the result
        assert result.extraction_method == "mistral-ocr"
        assert len(result.pages) == 1
        assert 0 in result.pages
        assert result.pages[0].markdown == "Extracted text from image"

    @pytest.mark.asyncio
    async def test_extract_with_content(self, processor):
        """Test extraction with content bytes."""
        content = b"fake image data"

        # Mock the OCR response
        mock_page = Mock()
        mock_page.index = 0
        mock_page.markdown = "Extracted text"
        mock_page.images = []  # No images in this example

        mock_response = Mock()
        mock_response.pages = [mock_page]

        processor._client.ocr.process = Mock(return_value=mock_response)

        _ = await processor._extract(content=content, content_type="image/png")

        # Check the API was called with base64 encoded content
        processor._client.ocr.process.assert_called_once()
        call_kwargs = processor._client.ocr.process.call_args.kwargs

        expected_data_url = f"data:image/png;base64,{base64.b64encode(content).decode('utf-8')}"
        assert call_kwargs["document"]["image_url"] == expected_data_url

    @pytest.mark.asyncio
    async def test_extract_pdf_with_pages(self, processor):
        """Test extraction with specific pages from PDF."""
        # Mock the OCR response
        mock_pages = []
        for i in [1, 3]:
            mock_page = Mock()
            mock_page.index = i
            mock_page.markdown = f"Text from page {i + 1}"
            mock_page.images = []  # No images in this example
            mock_pages.append(mock_page)

        mock_response = Mock()
        mock_response.pages = mock_pages

        processor._client.ocr.process = Mock(return_value=mock_response)

        result = await processor._extract(
            url="https://example.com/doc.pdf",
            content_type="application/pdf",
            pages=[1, 3],
        )

        # Check pages parameter is passed correctly
        call_kwargs = processor._client.ocr.process.call_args.kwargs
        assert call_kwargs["pages"] == [1, 3]  # Pages passed as-is to API
        assert call_kwargs["document"]["type"] == "document_url"

        # Check result has correct 0-indexed pages
        assert len(result.pages) == 2
        assert 1 in result.pages
        assert 3 in result.pages
        assert result.pages[1].markdown == "Text from page 2"
        assert result.pages[3].markdown == "Text from page 4"

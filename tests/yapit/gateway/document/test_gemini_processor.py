"""Tests for GeminiExtractor.

Integration tests require GOOGLE_API_KEY. Run with: make test-gemini
Unit tests for retry logic run without API key.
"""

import os
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from google.genai import errors as genai_errors

from yapit.contracts import YoloResult
from yapit.gateway.document.gemini import (
    MAX_RETRIES,
    GeminiExtractor,
)
from yapit.gateway.storage import LocalImageStorage

FIXTURES_DIR = Path("tests/fixtures/documents")


@pytest.fixture
def extractor(tmp_path):
    """Create a GeminiExtractor instance for testing."""
    if not os.getenv("GOOGLE_API_KEY"):
        pytest.skip("Requires GOOGLE_API_KEY")

    mock_settings = Mock()
    mock_settings.google_api_key = os.getenv("GOOGLE_API_KEY")
    mock_redis = AsyncMock()
    mock_redis.exists = AsyncMock(return_value=False)  # Not cancelled
    image_storage = LocalImageStorage(tmp_path / "images")

    return GeminiExtractor(settings=mock_settings, redis=mock_redis, image_storage=image_storage, resolution="low")


def _mock_yolo_result() -> YoloResult:
    """Create a mock YOLO result with no figures detected."""
    return YoloResult(
        job_id=uuid.uuid4(),
        figures=[],
        page_width=612,
        page_height=792,
        worker_id="mock",
        processing_time_ms=0,
    )


async def collect_pages(extractor_iter):
    """Helper to collect all pages from an async iterator."""
    pages = {}
    async for result in extractor_iter:
        if result.page is not None:
            pages[result.page_idx] = result.page
    return pages


@pytest.mark.gemini
@pytest.mark.asyncio
async def test_extract_pdf(extractor):
    """Extract text from a PDF."""
    with open(FIXTURES_DIR / "minimal.pdf", "rb") as f:
        content = f.read()

    with (
        patch("yapit.gateway.document.gemini.enqueue_detection", new_callable=AsyncMock, return_value="mock-job-id"),
        patch(
            "yapit.gateway.document.gemini.wait_for_result", new_callable=AsyncMock, return_value=_mock_yolo_result()
        ),
    ):
        pages = await collect_pages(
            extractor.extract(
                content=content,
                content_type="application/pdf",
                content_hash="test-minimal",
            )
        )

    assert pages
    assert pages[0].markdown.strip()


@pytest.mark.gemini
@pytest.mark.asyncio
async def test_extract_specific_pages(extractor):
    """Extract only requested pages from a multi-page PDF."""
    with open(FIXTURES_DIR / "multipage.pdf", "rb") as f:
        content = f.read()

    with (
        patch("yapit.gateway.document.gemini.enqueue_detection", new_callable=AsyncMock, return_value="mock-job-id"),
        patch(
            "yapit.gateway.document.gemini.wait_for_result", new_callable=AsyncMock, return_value=_mock_yolo_result()
        ),
    ):
        pages = await collect_pages(
            extractor.extract(
                content=content,
                content_type="application/pdf",
                content_hash="test-specific",
                pages=[0, 2],  # Skip page 1
            )
        )

    assert set(pages.keys()) == {0, 2}


@pytest.mark.gemini
@pytest.mark.asyncio
async def test_extract_image(extractor):
    """Extract text from an image."""
    with open(FIXTURES_DIR / "test.png", "rb") as f:
        content = f.read()

    pages = await collect_pages(
        extractor.extract(
            content=content,
            content_type="image/png",
            content_hash="test-png",
        )
    )

    assert 0 in pages


# --- Unit tests for retry logic (no API key required) ---


@pytest.fixture
def mock_extractor(tmp_path):
    """Create a GeminiExtractor with mocked client for unit testing."""
    mock_settings = Mock()
    mock_settings.google_api_key = "fake-key-for-testing"
    mock_redis = AsyncMock()
    image_storage = LocalImageStorage(tmp_path / "images")

    with patch("yapit.gateway.document.gemini.genai.Client"):
        extractor = GeminiExtractor(
            settings=mock_settings, redis=mock_redis, image_storage=image_storage, resolution="low"
        )
    return extractor


class TestRetryBehavior:
    """Tests for retry logic on API errors."""

    @pytest.mark.asyncio
    async def test_retries_on_429_rate_limit(self, mock_extractor):
        """Should retry on 429 rate limit and succeed on subsequent attempt."""
        mock_usage = Mock()
        mock_usage.prompt_token_count = 100
        mock_usage.candidates_token_count = 50
        mock_usage.thoughts_token_count = 10
        mock_usage.total_token_count = 160

        mock_response = Mock()
        mock_response.text = "Extracted text"
        mock_response.usage_metadata = mock_usage

        mock_extractor._client.models.generate_content = Mock(
            side_effect=[
                genai_errors.APIError(code=429, response_json={"error": {"message": "Rate limit"}}),
                genai_errors.APIError(code=429, response_json={"error": {"message": "Rate limit"}}),
                mock_response,
            ]
        )

        with (
            patch(
                "yapit.gateway.document.gemini.extract_single_page_pdf",
                return_value=b"fake-pdf-bytes",
            ),
            patch(
                "yapit.gateway.document.gemini.asyncio.sleep",
                new_callable=AsyncMock,
            ) as mock_sleep,
        ):
            result = await mock_extractor._call_gemini_for_page(
                pdf_reader=Mock(),
                page_idx=0,
                figures=[],
                figure_urls=[],
                content_hash="test-hash",
                user_id=None,
            )

        assert result.page is not None
        assert result.page.markdown == "Extracted text"
        assert mock_extractor._client.models.generate_content.call_count == 3
        assert mock_sleep.call_count == 2

    @pytest.mark.asyncio
    async def test_retries_on_server_errors(self, mock_extractor):
        """Should retry on 500, 503, 504 server errors."""
        mock_usage = Mock()
        mock_usage.prompt_token_count = 100
        mock_usage.candidates_token_count = 50
        mock_usage.thoughts_token_count = 10
        mock_usage.total_token_count = 160

        mock_response = Mock()
        mock_response.text = "Success after errors"
        mock_response.usage_metadata = mock_usage

        for error_code in [500, 503, 504]:
            mock_extractor._client.models.generate_content = Mock(
                side_effect=[
                    genai_errors.APIError(code=error_code, response_json={"error": {"message": "Server error"}}),
                    mock_response,
                ]
            )

            with (
                patch(
                    "yapit.gateway.document.gemini.extract_single_page_pdf",
                    return_value=b"fake-pdf-bytes",
                ),
                patch(
                    "yapit.gateway.document.gemini.asyncio.sleep",
                    new_callable=AsyncMock,
                ),
            ):
                result = await mock_extractor._call_gemini_for_page(
                    pdf_reader=Mock(),
                    page_idx=0,
                    figures=[],
                    figure_urls=[],
                    content_hash="test-hash",
                    user_id=None,
                )

            assert result.page is not None, f"Should succeed after {error_code} retry"

    @pytest.mark.asyncio
    async def test_no_retry_on_400_bad_request(self, mock_extractor):
        """Should NOT retry on 400 bad request - fails immediately."""
        mock_extractor._client.models.generate_content = Mock(
            side_effect=genai_errors.APIError(code=400, response_json={"error": {"message": "Bad request"}})
        )

        with patch(
            "yapit.gateway.document.gemini.extract_single_page_pdf",
            return_value=b"fake-pdf-bytes",
        ):
            result = await mock_extractor._call_gemini_for_page(
                pdf_reader=Mock(),
                page_idx=0,
                figures=[],
                figure_urls=[],
                content_hash="test-hash",
                user_id=None,
            )

        assert result.page is None
        assert mock_extractor._client.models.generate_content.call_count == 1

    @pytest.mark.asyncio
    async def test_no_retry_on_403_forbidden(self, mock_extractor):
        """Should NOT retry on 403 forbidden - fails immediately."""
        mock_extractor._client.models.generate_content = Mock(
            side_effect=genai_errors.APIError(code=403, response_json={"error": {"message": "Forbidden"}})
        )

        with patch(
            "yapit.gateway.document.gemini.extract_single_page_pdf",
            return_value=b"fake-pdf-bytes",
        ):
            result = await mock_extractor._call_gemini_for_page(
                pdf_reader=Mock(),
                page_idx=0,
                figures=[],
                figure_urls=[],
                content_hash="test-hash",
                user_id=None,
            )

        assert result.page is None
        assert mock_extractor._client.models.generate_content.call_count == 1

    @pytest.mark.asyncio
    async def test_no_retry_on_404_not_found(self, mock_extractor):
        """Should NOT retry on 404 not found - fails immediately."""
        mock_extractor._client.models.generate_content = Mock(
            side_effect=genai_errors.APIError(code=404, response_json={"error": {"message": "Not found"}})
        )

        with patch(
            "yapit.gateway.document.gemini.extract_single_page_pdf",
            return_value=b"fake-pdf-bytes",
        ):
            result = await mock_extractor._call_gemini_for_page(
                pdf_reader=Mock(),
                page_idx=0,
                figures=[],
                figure_urls=[],
                content_hash="test-hash",
                user_id=None,
            )

        assert result.page is None
        assert mock_extractor._client.models.generate_content.call_count == 1

    @pytest.mark.asyncio
    async def test_fails_after_max_retries_exhausted(self, mock_extractor):
        """Should return None after all retries exhausted."""
        mock_extractor._client.models.generate_content = Mock(
            side_effect=genai_errors.APIError(code=503, response_json={"error": {"message": "Unavailable"}})
        )

        with (
            patch(
                "yapit.gateway.document.gemini.extract_single_page_pdf",
                return_value=b"fake-pdf-bytes",
            ),
            patch(
                "yapit.gateway.document.gemini.asyncio.sleep",
                new_callable=AsyncMock,
            ),
        ):
            result = await mock_extractor._call_gemini_for_page(
                pdf_reader=Mock(),
                page_idx=0,
                figures=[],
                figure_urls=[],
                content_hash="test-hash",
                user_id=None,
            )

        assert result.page is None
        assert mock_extractor._client.models.generate_content.call_count == MAX_RETRIES

    @pytest.mark.asyncio
    async def test_retries_on_unexpected_exceptions(self, mock_extractor):
        """Should retry on unexpected exceptions (network errors, etc.)."""
        mock_usage = Mock()
        mock_usage.prompt_token_count = 100
        mock_usage.candidates_token_count = 50
        mock_usage.thoughts_token_count = 10
        mock_usage.total_token_count = 160

        mock_response = Mock()
        mock_response.text = "Success"
        mock_response.usage_metadata = mock_usage

        mock_extractor._client.models.generate_content = Mock(
            side_effect=[
                ConnectionError("Network failed"),
                mock_response,
            ]
        )

        with (
            patch(
                "yapit.gateway.document.gemini.extract_single_page_pdf",
                return_value=b"fake-pdf-bytes",
            ),
            patch(
                "yapit.gateway.document.gemini.asyncio.sleep",
                new_callable=AsyncMock,
            ),
        ):
            result = await mock_extractor._call_gemini_for_page(
                pdf_reader=Mock(),
                page_idx=0,
                figures=[],
                figure_urls=[],
                content_hash="test-hash",
                user_id=None,
            )

        assert result.page is not None
        assert mock_extractor._client.models.generate_content.call_count == 2

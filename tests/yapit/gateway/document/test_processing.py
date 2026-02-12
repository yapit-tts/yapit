"""Tests for document extraction orchestration (service.py).

These tests use fake extractors - no API calls, no complex mocking.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from yapit.gateway.document.processing import ExtractedPage, PageResult, ProcessorConfig, process_with_billing
from yapit.gateway.exceptions import ValidationError
from yapit.gateway.storage import ImageStorage


def make_config(
    slug: str = "test",
    is_paid: bool = False,
    extraction_cache_prefix: str | None = "test:v1",
) -> ProcessorConfig:
    return ProcessorConfig(
        slug=slug,
        supported_mime_types=frozenset({"application/pdf", "text/plain"}),
        max_pages=100,
        max_file_size=10 * 1024 * 1024,
        is_paid=is_paid,
        output_token_multiplier=6,
        extraction_cache_prefix=extraction_cache_prefix,
    )


async def fake_extractor(pages_to_yield: list[tuple[int, str]]):
    """Fake extractor that yields specified pages."""
    for page_idx, markdown in pages_to_yield:
        yield PageResult(
            page_idx=page_idx,
            page=ExtractedPage(markdown=markdown, images=[]),
            input_tokens=100,
            output_tokens=50,
            thoughts_tokens=10,
            is_fallback=False,
            cancelled=False,
        )


async def failing_extractor(fail_pages: set[int], total_pages: int):
    """Fake extractor where specified pages fail."""
    for page_idx in range(total_pages):
        if page_idx in fail_pages:
            yield PageResult(
                page_idx=page_idx,
                page=None,
                input_tokens=0,
                output_tokens=0,
                thoughts_tokens=0,
                is_fallback=False,
                cancelled=False,
            )
        else:
            yield PageResult(
                page_idx=page_idx,
                page=ExtractedPage(markdown=f"Page {page_idx}", images=[]),
                input_tokens=100,
                output_tokens=50,
                thoughts_tokens=10,
                is_fallback=False,
                cancelled=False,
            )


async def cancelled_extractor(cancel_after: int, total_pages: int):
    """Fake extractor where pages at or after cancel_after are cancelled."""
    for page_idx in range(total_pages):
        if page_idx >= cancel_after:
            yield PageResult(
                page_idx=page_idx,
                page=None,
                input_tokens=0,
                output_tokens=0,
                thoughts_tokens=0,
                is_fallback=False,
                cancelled=True,
            )
        else:
            yield PageResult(
                page_idx=page_idx,
                page=ExtractedPage(markdown=f"Page {page_idx}", images=[]),
                input_tokens=100,
                output_tokens=50,
                thoughts_tokens=10,
                is_fallback=False,
                cancelled=False,
            )


@pytest.fixture
def mock_db():
    return AsyncMock()


@pytest.fixture
def mock_cache():
    cache = AsyncMock()
    cache.retrieve_data = AsyncMock(return_value=None)  # No cache hits by default
    cache.batch_retrieve = AsyncMock(return_value={})
    cache.batch_exists = AsyncMock(return_value=set())
    cache.store = AsyncMock()
    cache.exists = AsyncMock(return_value=False)
    return cache


@pytest.fixture
def mock_image_storage():
    storage = AsyncMock(spec=ImageStorage)
    storage.exists = AsyncMock(return_value=True)
    return storage


@pytest.fixture
def mock_redis():
    return AsyncMock()


class TestValidation:
    @pytest.mark.asyncio
    async def test_rejects_unsupported_content_type(self, mock_db, mock_cache, mock_image_storage, mock_redis):
        config = make_config()

        with pytest.raises(ValidationError, match="Unsupported content type"):
            await process_with_billing(
                config=config,
                extractor=fake_extractor([]),
                user_id="user-1",
                content=b"test",
                content_type="image/png",  # Not in supported types
                content_hash="abc123",
                total_pages=1,
                db=mock_db,
                extraction_cache=mock_cache,
                image_storage=mock_image_storage,
                redis=mock_redis,
                billing_enabled=True,
            )

    @pytest.mark.asyncio
    async def test_rejects_too_many_pages(self, mock_db, mock_cache, mock_image_storage, mock_redis):
        config = make_config()

        with pytest.raises(ValidationError, match="maximum of 100 pages"):
            await process_with_billing(
                config=config,
                extractor=fake_extractor([]),
                user_id="user-1",
                content=b"test",
                content_type="application/pdf",
                content_hash="abc123",
                total_pages=101,  # Exceeds max_pages=100
                db=mock_db,
                extraction_cache=mock_cache,
                image_storage=mock_image_storage,
                redis=mock_redis,
                billing_enabled=True,
            )


class TestCaching:
    @pytest.mark.asyncio
    async def test_returns_cached_pages_without_extraction(self, mock_db, mock_cache, mock_image_storage, mock_redis):
        config = make_config()

        # Simulate cache hit for page 0 via batch_retrieve
        cached_page = ExtractedPage(markdown="Cached content", images=[]).model_dump_json().encode()
        cache_key = config.extraction_cache_key("abc123", 0)
        mock_cache.batch_retrieve = AsyncMock(return_value={cache_key: cached_page})

        extractor_called = False

        async def should_not_be_called():
            nonlocal extractor_called
            extractor_called = True
            yield

        result = await process_with_billing(
            config=config,
            extractor=should_not_be_called(),
            user_id="user-1",
            content=b"test",
            content_type="application/pdf",
            content_hash="abc123",
            total_pages=1,
            db=mock_db,
            extraction_cache=mock_cache,
            image_storage=mock_image_storage,
            redis=mock_redis,
            billing_enabled=True,
        )

        assert not extractor_called
        assert result.pages[0].markdown == "Cached content"

    @pytest.mark.asyncio
    async def test_stores_extracted_pages_to_cache(self, mock_db, mock_cache, mock_image_storage, mock_redis):
        config = make_config()

        result = await process_with_billing(
            config=config,
            extractor=fake_extractor([(0, "Fresh content")]),
            user_id="user-1",
            content=b"test",
            content_type="application/pdf",
            content_hash="abc123",
            total_pages=1,
            db=mock_db,
            extraction_cache=mock_cache,
            image_storage=mock_image_storage,
            redis=mock_redis,
            billing_enabled=True,
        )

        mock_cache.store.assert_called_once()
        assert result.pages[0].markdown == "Fresh content"


class TestBilling:
    @pytest.mark.asyncio
    async def test_paid_processor_checks_usage_limit(self, mock_db, mock_cache, mock_image_storage, mock_redis):
        config = make_config(is_paid=True)

        mock_estimate = Mock()
        mock_estimate.num_pages = 1
        mock_estimate.total_tokens = 1000

        with patch("yapit.gateway.document.processing.estimate_document_tokens", return_value=mock_estimate):
            with patch("yapit.gateway.document.processing.check_usage_limit", new_callable=AsyncMock) as mock_check:
                with patch("yapit.gateway.document.processing.record_usage", new_callable=AsyncMock):
                    await process_with_billing(
                        config=config,
                        extractor=fake_extractor([(0, "Content")]),
                        user_id="user-1",
                        content=b"test",
                        content_type="application/pdf",
                        content_hash="abc123",
                        total_pages=1,
                        db=mock_db,
                        extraction_cache=mock_cache,
                        image_storage=mock_image_storage,
                        redis=mock_redis,
                        billing_enabled=True,
                    )

                mock_check.assert_called_once()

    @pytest.mark.asyncio
    async def test_paid_processor_records_usage_per_page(self, mock_db, mock_cache, mock_image_storage, mock_redis):
        config = make_config(is_paid=True)

        mock_estimate = Mock()
        mock_estimate.num_pages = 3
        mock_estimate.total_tokens = 3000

        with patch("yapit.gateway.document.processing.estimate_document_tokens", return_value=mock_estimate):
            with patch("yapit.gateway.document.processing.check_usage_limit", new_callable=AsyncMock):
                with patch("yapit.gateway.document.processing.record_usage", new_callable=AsyncMock) as mock_record:
                    await process_with_billing(
                        config=config,
                        extractor=fake_extractor([(0, "Page 0"), (1, "Page 1"), (2, "Page 2")]),
                        user_id="user-1",
                        content=b"test",
                        content_type="application/pdf",
                        content_hash="abc123",
                        total_pages=3,
                        db=mock_db,
                        extraction_cache=mock_cache,
                        image_storage=mock_image_storage,
                        redis=mock_redis,
                        billing_enabled=True,
                    )

                assert mock_record.call_count == 3  # One per page

    @pytest.mark.asyncio
    async def test_free_processor_skips_billing(self, mock_db, mock_cache, mock_image_storage, mock_redis):
        config = make_config(is_paid=False)

        with patch("yapit.gateway.document.processing.check_usage_limit", new_callable=AsyncMock) as mock_check:
            with patch("yapit.gateway.document.processing.record_usage", new_callable=AsyncMock) as mock_record:
                await process_with_billing(
                    config=config,
                    extractor=fake_extractor([(0, "Content")]),
                    user_id="user-1",
                    content=b"test",
                    content_type="application/pdf",
                    content_hash="abc123",
                    total_pages=1,
                    db=mock_db,
                    extraction_cache=mock_cache,
                    image_storage=mock_image_storage,
                    redis=mock_redis,
                    billing_enabled=True,
                )

            mock_check.assert_not_called()
            mock_record.assert_not_called()


class TestFailedPages:
    @pytest.mark.asyncio
    async def test_tracks_failed_pages(self, mock_db, mock_cache, mock_image_storage, mock_redis):
        config = make_config()

        result = await process_with_billing(
            config=config,
            extractor=failing_extractor(fail_pages={1}, total_pages=3),
            user_id="user-1",
            content=b"test",
            content_type="application/pdf",
            content_hash="abc123",
            total_pages=3,
            db=mock_db,
            extraction_cache=mock_cache,
            image_storage=mock_image_storage,
            redis=mock_redis,
            billing_enabled=True,
        )

        assert set(result.pages.keys()) == {0, 2}
        assert result.failed_pages == [1]


class TestCancellation:
    @pytest.mark.asyncio
    async def test_cancelled_pages_not_billed(self, mock_db, mock_cache, mock_image_storage, mock_redis):
        """Cancelled pages should not incur billing charges."""
        config = make_config(is_paid=True)

        mock_estimate = Mock()
        mock_estimate.num_pages = 4
        mock_estimate.total_tokens = 4000

        with patch("yapit.gateway.document.processing.estimate_document_tokens", return_value=mock_estimate):
            with patch("yapit.gateway.document.processing.check_usage_limit", new_callable=AsyncMock):
                with patch("yapit.gateway.document.processing.record_usage", new_callable=AsyncMock) as mock_record:
                    await process_with_billing(
                        config=config,
                        extractor=cancelled_extractor(cancel_after=2, total_pages=4),
                        user_id="user-1",
                        content=b"test",
                        content_type="application/pdf",
                        content_hash="abc123",
                        total_pages=4,
                        db=mock_db,
                        extraction_cache=mock_cache,
                        image_storage=mock_image_storage,
                        redis=mock_redis,
                        billing_enabled=True,
                    )

                    # Only pages 0 and 1 should be billed (pages 2, 3 cancelled)
                    assert mock_record.call_count == 2

"""Document extraction models, billing orchestration, and token estimation."""

from collections.abc import AsyncIterator
from dataclasses import dataclass

from loguru import logger
from pydantic import BaseModel, ConfigDict
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.cache import Cache
from yapit.gateway.config import Settings
from yapit.gateway.constants import SUPPORTED_DOCUMENT_MIME_TYPES
from yapit.gateway.document.extraction import PER_PAGE_TOLERANCE, estimate_document_tokens
from yapit.gateway.domain_models import DocumentMetadata, UsageType
from yapit.gateway.exceptions import ValidationError
from yapit.gateway.metrics import log_event
from yapit.gateway.usage import check_usage_limit, record_usage


class ExtractedPage(BaseModel):
    """Single page extraction result."""

    markdown: str
    images: list[str]  # URLs to stored images (e.g., /images/{hash}/0.png)


class DocumentExtractionResult(BaseModel):
    """Unified extraction result from any processor."""

    pages: dict[int, ExtractedPage]
    extraction_method: str
    failed_pages: list[int] = []  # Pages that failed after all retries


class CachedDocument(BaseModel):
    """Structure stored in cache for documents."""

    metadata: DocumentMetadata
    content: bytes | None = None  # file content (if not webpage or plain text)
    extraction: DocumentExtractionResult | None = None

    model_config = ConfigDict(
        ser_json_bytes="base64",
        val_json_bytes="base64",
    )


@dataclass
class PageResult:
    """Result of processing a single page, yielded by extractors."""

    page_idx: int
    page: ExtractedPage | None  # None if extraction failed
    input_tokens: int
    output_tokens: int
    thoughts_tokens: int
    is_fallback: bool
    cancelled: bool


@dataclass(frozen=True)
class ProcessorConfig:
    """Configuration for a document processor.

    Separates static config (what a processor can do) from runtime behavior (extraction).
    """

    slug: str
    supported_mime_types: frozenset[str]
    max_pages: int
    max_file_size: int
    is_paid: bool
    output_token_multiplier: int
    extraction_cache_prefix: str | None

    def get_supported_mime_types(self) -> set[str]:
        """Expand wildcards (e.g. 'image/*') against platform-supported types."""
        supported = set()
        for proc_type in self.supported_mime_types:
            if proc_type.endswith("/*"):
                prefix = proc_type[:-2]
                supported.update(t for t in SUPPORTED_DOCUMENT_MIME_TYPES if t.startswith(prefix + "/"))
            elif proc_type in SUPPORTED_DOCUMENT_MIME_TYPES:
                supported.add(proc_type)
        return supported

    def is_supported(self, mime_type: str) -> bool:
        # Strip parameters (e.g., "image/jpeg; qs=0.8" -> "image/jpeg")
        base_type = mime_type.split(";")[0].strip()
        return base_type in self.get_supported_mime_types()

    def extraction_cache_key(self, content_hash: str, page_idx: int) -> str:
        return f"{content_hash}:{self.extraction_cache_prefix}:{page_idx}"


type Extractor = AsyncIterator[PageResult]


async def process_with_billing(
    config: ProcessorConfig,
    extractor: Extractor,
    user_id: str,
    content: bytes,
    content_type: str,
    content_hash: str,
    total_pages: int,
    db: AsyncSession,
    extraction_cache: Cache,
    settings: Settings,
    file_size: int | None = None,
    pages: list[int] | None = None,
) -> DocumentExtractionResult:
    """Orchestrate document extraction with validation, caching, and billing.

    1. Validate content type and limits
    2. Check extraction cache for already-processed pages
    3. Estimate tokens and check usage limit (paid processors)
    4. Extract uncached pages, caching and billing each as it completes
    5. Return merged result (cached + fresh pages)
    """
    # 1. Validate
    if not config.is_supported(content_type):
        raise ValidationError(
            f"Unsupported content type: {content_type}. Supported types: {config.get_supported_mime_types()}"
        )
    if total_pages > config.max_pages:
        raise ValidationError(
            f"Document has {total_pages} pages, but this processor supports a maximum of {config.max_pages} pages."
        )
    if file_size and file_size > config.max_file_size:
        raise ValidationError(
            f"Document size {file_size} bytes exceeds the maximum allowed size of {config.max_file_size} bytes."
        )

    # 2. Check extraction cache
    requested_pages = set(pages) if pages else set(range(total_pages))
    cached_pages: dict[int, ExtractedPage] = {}
    uncached_pages: set[int] = set()

    if config.extraction_cache_prefix:
        for page_idx in requested_pages:
            cache_key = config.extraction_cache_key(content_hash, page_idx)
            data = await extraction_cache.retrieve_data(cache_key)
            if data:
                cached_pages[page_idx] = ExtractedPage.model_validate_json(data)
                await log_event("extraction_cache_hit", processor_slug=config.slug, page_idx=page_idx, user_id=user_id)
            else:
                uncached_pages.add(page_idx)
    else:
        uncached_pages = requested_pages

    if not uncached_pages:
        return DocumentExtractionResult(pages=cached_pages, extraction_method=config.slug)

    # 3. Check usage limit (paid processors only)
    if config.is_paid:
        estimate = estimate_document_tokens(content, content_type, config.output_token_multiplier, list(uncached_pages))
        tolerance = PER_PAGE_TOLERANCE * estimate.num_pages
        amount_to_check = max(0, estimate.total_tokens - tolerance)

        await log_event(
            "extraction_estimate",
            processor_slug=config.slug,
            user_id=user_id,
            data={
                "content_hash": content_hash,
                "num_pages": estimate.num_pages,
                "text_pages": estimate.text_pages,
                "raster_pages": estimate.raster_pages,
                "total_text_chars": estimate.total_text_chars,
                "estimated_tokens": estimate.total_tokens,
                "tolerance": tolerance,
                "amount_checked": amount_to_check,
            },
        )

        await check_usage_limit(
            user_id,
            UsageType.ocr_tokens,
            amount_to_check,
            db,
            billing_enabled=settings.billing_enabled,
        )

    # 4. Extract, cache, and bill each page as it completes
    fresh_pages: dict[int, ExtractedPage] = {}
    failed_pages: list[int] = []

    async for result in extractor:
        if result.cancelled:
            logger.info(f"Page {result.page_idx + 1} was cancelled")
            continue

        if result.page is None:
            failed_pages.append(result.page_idx)
            continue

        fresh_pages[result.page_idx] = result.page

        # Cache immediately
        if config.extraction_cache_prefix:
            cache_key = config.extraction_cache_key(content_hash, result.page_idx)
            await extraction_cache.store(cache_key, result.page.model_dump_json().encode())

        # Bill immediately (paid processors only)
        if config.is_paid:
            token_equiv = (
                result.input_tokens + (result.output_tokens + result.thoughts_tokens) * config.output_token_multiplier
            )
            await record_usage(
                user_id=user_id,
                usage_type=UsageType.ocr_tokens,
                amount=token_equiv,
                db=db,
                reference_id=content_hash,
                description=f"Page {result.page_idx + 1} extraction with {config.slug}",
                details={
                    "processor": config.slug,
                    "page_idx": result.page_idx,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "thoughts_tokens": result.thoughts_tokens,
                    "token_equiv": token_equiv,
                    "is_fallback": result.is_fallback,
                },
            )

    # 5. Merge cached + fresh, sort by page index
    all_pages = {**cached_pages, **fresh_pages}
    sorted_pages = dict(sorted(all_pages.items()))

    return DocumentExtractionResult(
        pages=sorted_pages,
        extraction_method=config.slug,
        failed_pages=failed_pages,
    )

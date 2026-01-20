from abc import abstractmethod

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


class TokenUsage(BaseModel):
    """Token usage data for billing (from paid processors like Gemini)."""

    input_tokens: int
    output_tokens: int
    thoughts_tokens: int = 0
    token_equiv: int  # input + (output + thoughts) × multiplier — what we bill
    is_fallback: bool = False  # True if using estimated values (usage_metadata was None)


class DocumentExtractionResult(BaseModel):
    """Unified extraction result from any processor."""

    pages: dict[int, ExtractedPage]
    extraction_method: str
    failed_pages: list[int] = []  # Pages that failed after all retries
    token_usage: TokenUsage | None = None  # For paid processors that bill by tokens


class CachedDocument(BaseModel):
    """Structure stored in cache for documents."""

    metadata: DocumentMetadata
    content: bytes | None = None  # file content (if not webpage or plain text)
    extraction: DocumentExtractionResult | None = None

    model_config = ConfigDict(
        ser_json_bytes="base64",
        val_json_bytes="base64",
    )


class BaseDocumentProcessor:
    """Base class for all document processors."""

    def __init__(self, settings: Settings, slug: str, **kwargs) -> None:
        self._settings = settings
        self._slug = slug

    @property
    def _extraction_key_prefix(self) -> str | None:
        """Return prefix for extraction cache keys, or None to disable extraction caching.

        Format: "{processor}:{config_that_affects_output}"
        Full key will be: "{content_hash}:{prefix}:{page_idx}"
        """
        return None

    @property
    @abstractmethod
    def _processor_supported_mime_types(self) -> set[str]:
        """Return set of MIME types this processor can handle.

        Can include wildcards like 'image/*' or specific types like 'application/pdf'.
        This should return ALL formats the processor technically supports.
        """

    @property
    @abstractmethod
    def max_pages(self) -> int:
        """Maximum number of pages this processor can handle for one document."""

    @property
    @abstractmethod
    def max_file_size(self) -> int:
        """Maximum file size in bytes this processor can handle for uploads."""

    @property
    def is_paid(self) -> bool:
        """Whether this processor requires usage tracking (counts against OCR limit)."""
        return False

    @property
    def output_token_multiplier(self) -> int:
        """Cost multiplier for output tokens (e.g., 6 for Gemini where output costs 6x input).

        Override in paid processors.
        """
        return 1

    @abstractmethod
    async def _extract(
        self,
        content: bytes,
        content_type: str,
        content_hash: str,
        extraction_cache: Cache,
        pages: list[int] | None = None,
    ) -> DocumentExtractionResult:
        """Extract text from document, caching pages as they complete."""

    @property
    def supported_mime_types(self) -> set[str]:
        """Return intersection of processor capabilities and platform-supported types.

        Processors can use wildcards like 'image/*' which will match all platform
        types starting with 'image/'.
        """
        processor_types = self._processor_supported_mime_types
        supported = set()

        for proc_type in processor_types:
            if proc_type.endswith("/*"):
                # Handle wildcards like "image/*"
                prefix = proc_type[:-2]
                supported.update(t for t in SUPPORTED_DOCUMENT_MIME_TYPES if t.startswith(prefix + "/"))
            elif proc_type in SUPPORTED_DOCUMENT_MIME_TYPES:
                supported.add(proc_type)

        return supported

    def _extraction_cache_key(self, content_hash: str, page_idx: int) -> str:
        """Build extraction cache key for a page."""
        return f"{content_hash}:{self._extraction_key_prefix}:{page_idx}"

    async def process_with_billing(
        self,
        user_id: str,
        content_hash: str,
        db: AsyncSession,
        extraction_cache: Cache,
        content_type: str,
        content: bytes,
        total_pages: int,
        file_size: int | None = None,
        pages: list[int] | None = None,
        is_admin: bool = False,
    ) -> DocumentExtractionResult:
        """Process document with caching and usage tracking."""
        if not self._is_supported(content_type):
            raise ValidationError(
                f"Unsupported content type: {content_type}. Supported types: {self.supported_mime_types}"
            )

        if total_pages > self.max_pages:
            raise ValidationError(
                f"Document has {total_pages} pages, but this processor supports a maximum of {self.max_pages} pages."
            )
        if file_size and file_size > self.max_file_size:
            raise ValidationError(
                f"Document size {file_size}MB exceeds the maximum allowed size of {self.max_file_size}MB."
            )

        requested_pages = set(pages) if pages else set(range(total_pages))
        cached_pages: dict[int, ExtractedPage] = {}
        uncached_pages: set[int] = set()

        # Check extraction cache for each requested page
        if self._extraction_key_prefix:
            for page_idx in requested_pages:
                cache_key = self._extraction_cache_key(content_hash, page_idx)
                data = await extraction_cache.retrieve_data(cache_key)
                if data:
                    cached_pages[page_idx] = ExtractedPage.model_validate_json(data)
                else:
                    uncached_pages.add(page_idx)
        else:
            uncached_pages = requested_pages

        # All pages cached — return immediately
        if not uncached_pages:
            await log_event(
                "extraction_cache_hit",
                processor_slug=self._slug,
                data={"pages_hit": len(cached_pages)},
            )
            return DocumentExtractionResult(pages=cached_pages, extraction_method=self._slug)

        # Check usage limit before processing (only for paid processors)
        # Estimate tokens from actual content using PyMuPDF text extraction
        # Buffer favors user: allow estimate to exceed balance by per-page tolerance
        if self.is_paid:
            estimate = estimate_document_tokens(
                content, content_type, self.output_token_multiplier, list(uncached_pages)
            )
            tolerance = PER_PAGE_TOLERANCE * estimate.num_pages
            # Subtract tolerance from estimate — effectively gives user extra headroom
            # If estimate=55K, tolerance=10K, we check if user has 45K (not 55K)
            amount_to_check = max(0, estimate.total_tokens - tolerance)

            await log_event(
                "extraction_estimate",
                processor_slug=self._slug,
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
                is_admin=is_admin,
                billing_enabled=self._settings.billing_enabled,
            )

        # Process missing pages (processor caches each page as it completes)
        result = await self._extract(
            content=content,
            content_type=content_type,
            content_hash=content_hash,
            extraction_cache=extraction_cache,
            pages=list(uncached_pages),
        )

        # Bill actual tokens after extraction (server-side processing continues even if client disconnects)
        if self.is_paid and result.token_usage:
            await record_usage(
                user_id=user_id,
                usage_type=UsageType.ocr_tokens,
                amount=result.token_usage.token_equiv,
                db=db,
                reference_id=content_hash,
                description=f"Document processing: {len(result.pages)} pages with {self._slug}",
                details={
                    "processor": self._slug,
                    "pages_extracted": len(result.pages),
                    "pages_failed": len(result.failed_pages),
                    "input_tokens": result.token_usage.input_tokens,
                    "output_tokens": result.token_usage.output_tokens,
                    "thoughts_tokens": result.token_usage.thoughts_tokens,
                    "token_equiv": result.token_usage.token_equiv,
                    "is_fallback": result.token_usage.is_fallback,
                },
            )

        # Merge and sort by page index to ensure consistent ordering
        all_pages = {**cached_pages, **result.pages}
        sorted_pages = {k: all_pages[k] for k in sorted(all_pages.keys())}

        # Preserve token_usage from extraction for API response
        return DocumentExtractionResult(
            pages=sorted_pages,
            extraction_method=self._slug,
            failed_pages=result.failed_pages,
            token_usage=result.token_usage,
        )

    def _is_supported(self, mime_type: str) -> bool:
        """Check if this processor supports the given MIME type."""
        # Strip parameters (e.g., "image/jpeg; qs=0.8" -> "image/jpeg")
        base_type = mime_type.split(";")[0].strip()
        return base_type in self.supported_mime_types

from abc import abstractmethod

from pydantic import BaseModel, ConfigDict
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.cache import Cache
from yapit.gateway.config import Settings
from yapit.gateway.constants import SUPPORTED_DOCUMENT_MIME_TYPES
from yapit.gateway.domain_models import DocumentMetadata, UsageType
from yapit.gateway.exceptions import ValidationError
from yapit.gateway.usage import check_usage_limit, record_usage


class ExtractedPage(BaseModel):
    """Single page extraction result."""

    markdown: str
    images: list[str]  # URLs to stored images (e.g., /images/{hash}/0.png)


class DocumentExtractionResult(BaseModel):
    """Unified extraction result from any processor."""

    pages: dict[int, ExtractedPage]
    extraction_method: str


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

    @abstractmethod
    async def _extract(
        self,
        content: bytes,
        content_type: str,
        content_hash: str,
        pages: list[int] | None = None,
    ) -> DocumentExtractionResult:
        """Extract text from document."""

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
            return DocumentExtractionResult(pages=cached_pages, extraction_method=self._slug)

        # Check usage limit before processing (only for paid processors)
        if self.is_paid:
            await check_usage_limit(
                user_id,
                UsageType.ocr,
                len(uncached_pages),
                db,
                is_admin=is_admin,
                billing_enabled=self._settings.billing_enabled,
            )

        # Process missing pages
        result = await self._extract(
            content=content,
            content_type=content_type,
            content_hash=content_hash,
            pages=list(uncached_pages),
        )

        # Store new pages in extraction cache
        if self._extraction_key_prefix:
            for page_idx, page in result.pages.items():
                cache_key = self._extraction_cache_key(content_hash, page_idx)
                await extraction_cache.store(cache_key, page.model_dump_json().encode())

        # Record usage for processed pages (only for paid processors)
        if self.is_paid and result.pages:
            await record_usage(
                user_id=user_id,
                usage_type=UsageType.ocr,
                amount=len(result.pages),
                db=db,
                reference_id=content_hash,
                description=f"Document processing: {len(result.pages)} pages with {self._slug}",
                details={
                    "processor": self._slug,
                    "pages_processed": len(result.pages),
                    "page_numbers": list(result.pages.keys()),
                },
            )

        all_pages = {**cached_pages, **result.pages}
        return DocumentExtractionResult(pages=all_pages, extraction_method=self._slug)

    def _is_supported(self, mime_type: str) -> bool:
        """Check if this processor supports the given MIME type."""
        # Strip parameters (e.g., "image/jpeg; qs=0.8" -> "image/jpeg")
        base_type = mime_type.split(";")[0].strip()
        return base_type in self.supported_mime_types

from abc import abstractmethod

from pydantic import BaseModel, ConfigDict
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.cache import Cache
from yapit.gateway.config import Settings
from yapit.gateway.constants import SUPPORTED_DOCUMENT_MIME_TYPES
from yapit.gateway.domain_models import DocumentMetadata, UsageType
from yapit.gateway.exceptions import ResourceNotFoundError, ValidationError
from yapit.gateway.usage import check_usage_limit, record_usage


class ExtractedPage(BaseModel):
    """Single page extraction result.

    Args:
        markdown: Full markdown content of the page, including tables and image placeholders if available: [img-<idx>.jpeg](img-<idx>.jpeg)
        images: List of base64 encoded images extracted from the page.
    """

    markdown: str
    images: list[str]


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
        content_type: str,
        url: str | None = None,
        content: bytes | None = None,
        pages: list[int] | None = None,
    ) -> DocumentExtractionResult:
        """Extract text from document. Always includes images if available.

        Args:
            content_type: MIME type of the document
            url: URL of the document to process (optional)
            content: Raw bytes of the document (optional)
            pages: Specific pages to process (optional)
        """

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

    async def process_with_billing(
        self,
        user_id: str,
        cache_key: str,
        db: AsyncSession,
        cache: Cache,
        content_type: str,
        url: str | None = None,
        content: bytes | None = None,
        pages: list[int] | None = None,
        is_admin: bool = False,
    ) -> DocumentExtractionResult:
        """Process document with caching and usage tracking."""
        if url is None and content is None:
            raise ValidationError("At least one of 'url' or 'content' must be provided")
        if not self._is_supported(content_type):
            raise ValidationError(
                f"Unsupported content type: {content_type}. Supported types: {self.supported_mime_types}"
            )

        cached_data = await cache.retrieve_data(cache_key)
        if not cached_data:
            raise ResourceNotFoundError(
                CachedDocument.__name__, cache_key, message=f"Document with key {cache_key!r} not found in cache"
            )
        cached_doc = CachedDocument.model_validate_json(cached_data)

        if cached_doc.metadata.total_pages > self.max_pages:
            raise ValidationError(
                f"Document has {cached_doc.metadata.total_pages} pages, but this processor supports a maximum of {self.max_pages} pages."
            )
        if cached_doc.metadata.file_size and cached_doc.metadata.file_size > self.max_file_size:
            raise ValidationError(
                f"Document size {cached_doc.metadata.file_size}MB exceeds the maximum allowed size of {self.max_file_size}MB."
            )

        # Initialize extraction if needed
        if not cached_doc.extraction:
            cached_doc.extraction = DocumentExtractionResult(pages={}, extraction_method=self._slug)

        # Determine what pages to process
        uncached_pages = get_uncached_pages(cached_doc, pages)
        requested_pages = set(pages) if pages else set(range(cached_doc.metadata.total_pages))

        # If all pages are cached, return them
        if not uncached_pages:
            return self._filter_pages(cached_doc.extraction, requested_pages)

        # Check usage limit before processing (only for paid processors like OCR)
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
        result = await self._extract(url=url, content=content, content_type=content_type, pages=list(uncached_pages))

        # Merge results
        cached_doc.extraction.pages.update(result.pages)

        # Update cache
        await cache.store(
            cache_key,
            cached_doc.model_dump_json().encode(),
            ttl_seconds=self._settings.document_cache_ttl_document,
        )

        # Record usage for processed pages (only for paid processors)
        if self.is_paid and result.pages:
            await record_usage(
                user_id=user_id,
                usage_type=UsageType.ocr,
                amount=len(result.pages),
                db=db,
                reference_id=cache_key,
                description=f"Document processing: {len(result.pages)} pages with {self._slug}",
                details={
                    "processor": self._slug,
                    "pages_processed": len(result.pages),
                    "page_numbers": list(result.pages.keys()),
                },
            )

        return self._filter_pages(cached_doc.extraction, requested_pages)

    @staticmethod
    def _filter_pages(extraction: DocumentExtractionResult, requested_pages: set[int]) -> DocumentExtractionResult:
        """Filter extraction result to only include requested pages."""
        return DocumentExtractionResult(
            pages={idx: page for idx, page in extraction.pages.items() if idx in requested_pages},
            extraction_method=extraction.extraction_method,
        )

    def _is_supported(self, mime_type: str) -> bool:
        """Check if this processor supports the given MIME type."""
        return mime_type in self.supported_mime_types


def get_uncached_pages(
    cached_doc: CachedDocument,
    requested_pages: list[int] | None = None,
) -> set[int]:
    """Get pages that need processing.

    Args:
        cached_doc: The cached document with existing extraction results
        requested_pages: Specific pages to process (None or empty means all)

    Returns:
        Set of page numbers that need processing
    """
    existing_pages = set(cached_doc.extraction.pages.keys()) if cached_doc.extraction else set()
    pages_to_process = set(requested_pages) if requested_pages else set(range(cached_doc.metadata.total_pages))
    return pages_to_process - existing_pages

from abc import ABC, abstractmethod
from decimal import Decimal

from pydantic import BaseModel, ConfigDict
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.cache import SqliteCache
from yapit.gateway.config import Settings
from yapit.gateway.constants import PLATFORM_SUPPORTED_MIME_TYPES
from yapit.gateway.db import get_by_slug_or_404
from yapit.gateway.domain_models import (
    CreditTransaction,
    DocumentMetadata,
    DocumentProcessor,
    TransactionType,
    UserCredits,
)
from yapit.gateway.exceptions import InsufficientCreditsError, ResourceNotFoundError, ValidationError


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


class BaseDocumentProcessor(ABC):
    """Base class for all document processors."""

    def __init__(self, slug: str, settings: Settings, **kwargs):
        self.processor_slug = slug
        self.settings = settings

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
                supported.update(t for t in PLATFORM_SUPPORTED_MIME_TYPES if t.startswith(prefix + "/"))
            elif proc_type in PLATFORM_SUPPORTED_MIME_TYPES:
                supported.add(proc_type)

        return supported

    async def process_with_billing(
        self,
        user_id: str,
        user_credits: UserCredits,
        cache_key: str,
        db: AsyncSession,
        cache: SqliteCache,
        content_type: str,
        url: str | None = None,
        content: bytes | None = None,
        pages: list[int] | None = None,
    ) -> DocumentExtractionResult:
        """Process document with caching and billing."""
        if url is None and content is None:
            raise ValidationError("At least one of 'url' or 'content' must be provided")
        if not self._is_supported(content_type):
            raise ValidationError(
                f"Unsupported content type: {content_type}. Supported types: {self.supported_mime_types}"
            )

        processor_model = await get_by_slug_or_404(db, DocumentProcessor, self.processor_slug)

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
            cached_doc.extraction = DocumentExtractionResult(pages={}, extraction_method=self.processor_slug)

        # Determine what pages to process
        missing_pages = get_missing_pages(cached_doc, pages)
        requested_pages = set(pages) if pages else set(range(cached_doc.metadata.total_pages))

        # If all pages are cached, return them
        if not missing_pages:
            return self._filter_pages(cached_doc.extraction, requested_pages)

        # Check credits
        credits_needed = Decimal(len(missing_pages)) * processor_model.credits_per_page
        if user_credits.balance < credits_needed:
            raise InsufficientCreditsError(required=credits_needed, available=user_credits.balance)

        # Process missing pages
        result = await self._extract(url=url, content=content, content_type=content_type, pages=list(missing_pages))

        # Merge results
        cached_doc.extraction.pages.update(result.pages)

        # Update cache
        await cache.store(
            cache_key,
            cached_doc.model_dump_json().encode(),
            ttl_seconds=self.settings.document_cache_ttl_document,
        )

        # Bill for processed pages
        actual_credits = Decimal(len(result.pages)) * processor_model.credits_per_page
        if actual_credits > 0:
            await self._create_transaction(db, user_id, user_credits, actual_credits, result.pages, cache_key)

        return self._filter_pages(cached_doc.extraction, requested_pages)

    @staticmethod
    def _filter_pages(extraction: DocumentExtractionResult, requested_pages: set[int]) -> DocumentExtractionResult:
        """Filter extraction result to only include requested pages."""
        return DocumentExtractionResult(
            pages={idx: page for idx, page in extraction.pages.items() if idx in requested_pages},
            extraction_method=extraction.extraction_method,
        )

    async def _create_transaction(
        self,
        db: AsyncSession,
        user_id: str,
        user_credits: UserCredits,
        credits: Decimal,
        processed_pages: dict[int, ExtractedPage],
        cache_key: str,
    ) -> None:
        """Create billing transaction."""
        transaction = CreditTransaction(
            user_id=user_id,
            type=TransactionType.usage_deduction,
            amount=-credits,
            balance_before=user_credits.balance,
            balance_after=user_credits.balance - credits,
            description=f"Document processing: {len(processed_pages)} pages with {self.processor_slug}",
            usage_reference=cache_key,
            details={
                "processor": self.processor_slug,
                "pages_processed": len(processed_pages),
                "page_numbers": list(processed_pages.keys()),
            },
        )
        db.add(transaction)
        user_credits.balance -= credits
        await db.commit()

    def _is_supported(self, mime_type: str) -> bool:
        """Check if this processor supports the given MIME type."""
        return mime_type in self.supported_mime_types


def get_missing_pages(
    cached_doc: CachedDocument,
    requested_pages: list[int] | None = None,
) -> set[int]:
    """Get pages that need processing (not in cache).

    Args:
        cached_doc: The cached document with existing extraction results
        requested_pages: Specific pages to process (None or empty means all)

    Returns:
        Set of page numbers that need processing
    """
    existing_pages = set(cached_doc.extraction.pages.keys()) if cached_doc.extraction else set()
    pages_to_process = set(requested_pages) if requested_pages else set(range(cached_doc.metadata.total_pages))
    return pages_to_process - existing_pages


def calculate_credit_cost(
    cached_doc: CachedDocument,
    processor_credits_per_page: Decimal,
    requested_pages: list[int] | None = None,
) -> Decimal:
    """Calculate credit cost for processing pages, accounting for cached pages.

    Args:
        cached_doc: The cached document with existing extraction results
        processor_credits_per_page: Credits per page for the processor
        requested_pages: Specific pages to process (None means all)

    Returns:
        Total credit cost for uncached pages
    """
    missing_pages = get_missing_pages(cached_doc, requested_pages)
    return Decimal(len(missing_pages)) * processor_credits_per_page

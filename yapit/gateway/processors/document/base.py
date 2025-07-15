from abc import ABC, abstractmethod
from decimal import Decimal

from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.cache import SqliteCache
from yapit.gateway.config import Settings
from yapit.gateway.domain_models import (
    CreditTransaction,
    DocumentMetadata,
    DocumentProcessor,
    TransactionType,
    UserCredits,
)


class ExtractedPage(BaseModel):
    """Single page extraction result."""

    markdown: str  # Full markdown with images/tables/latex


class DocumentExtractionResult(BaseModel):
    """Unified extraction result from any processor."""

    pages: dict[int, ExtractedPage]  # 1-indexed !
    extraction_method: str
    # TODO: Consider adding extraction settings here if we support multiple configs


class CachedDocument(BaseModel):
    """Structure stored in cache for documents."""

    metadata: DocumentMetadata
    content: bytes | None = None  # Optional - actual file content for uploads
    extraction: DocumentExtractionResult | None = None


class BaseDocumentProcessor(ABC):
    """Base class for all document processors."""

    def __init__(self, processor_slug: str, settings: Settings, **kwargs):
        self.processor_slug = processor_slug
        self.settings = settings

    @abstractmethod
    def supported_mime_types(self) -> set[str]:
        """Return set of supported MIME types.

        Can include wildcards like 'image/*' or specific types like 'application/pdf'.
        """
        pass

    def is_supported(self, mime_type: str) -> bool:
        """Check if this processor supports the given MIME type."""
        for supported in self.supported_mime_types():
            if supported.endswith("/*"):
                # Wildcard match (e.g., "image/*")
                prefix = supported[:-2]
                if mime_type.startswith(prefix + "/"):
                    return True
            elif mime_type == supported:
                return True
        return False

    @abstractmethod
    async def _extract(
        self,
        url: str | None = None,
        content: bytes | None = None,
        content_type: str | None = None,
        pages: list[int] | None = None,
    ) -> DocumentExtractionResult:
        """Extract text from document. Always includes images if available.

        Either url or content must be provided.
        - url: For processors that can fetch content themselves (e.g., Mistral)
        - content: For processors that need the actual file bytes
        - content_type: MIME type (required when content is provided)
        """
        pass

    async def process_with_billing(
        self,
        user_id: str,
        cache_key: str,
        db: AsyncSession,
        cache: SqliteCache,
        url: str | None = None,
        content: bytes | None = None,
        content_type: str | None = None,
        pages: list[int] | None = None,
    ) -> DocumentExtractionResult:
        """Process document with caching and billing."""
        # Get processor config
        result = await db.exec(select(DocumentProcessor).where(DocumentProcessor.slug == self.processor_slug))
        processor_model = result.first()
        if not processor_model:
            raise ValueError(f"Document processor '{self.processor_slug}' not found in database")

        # Get cached document
        cached_data = await cache.retrieve_data(cache_key)
        if not cached_data:
            raise ValueError("Document not found in cache. Please prepare document first.")

        cached_doc = CachedDocument.model_validate_json(cached_data)

        # Initialize extraction if needed
        if not cached_doc.extraction:
            cached_doc.extraction = DocumentExtractionResult(pages={}, extraction_method=self.processor_slug)

        # Determine what pages to process
        missing_pages = get_missing_pages(cached_doc, pages)
        requested_pages = set(pages) if pages else set(range(1, cached_doc.metadata.total_pages + 1))

        # If all pages are cached, return them
        if not missing_pages:
            return self._filter_pages(cached_doc.extraction, requested_pages)

        # Check credits
        user_credits = await db.get(UserCredits, user_id)
        if not user_credits:
            raise ValueError("User credits not found")

        credits_needed = Decimal(len(missing_pages)) * processor_model.credits_per_page
        if user_credits.balance < credits_needed:
            raise ValueError(f"Insufficient credits: need {credits_needed}, have {user_credits.balance}")

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

    async def _create_transaction(  # TODO dont use a function here..
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


def get_missing_pages(
    cached_doc: CachedDocument,
    requested_pages: list[int] | None = None,
) -> set[int]:
    """Get pages that need processing (not in cache).

    Args:
        cached_doc: The cached document with existing extraction results
        requested_pages: Specific pages to process (None means all)

    Returns:
        Set of page numbers that need processing
    """
    existing_pages = set()
    if cached_doc.extraction:
        existing_pages = set(cached_doc.extraction.pages.keys())
    if requested_pages:
        pages_to_process = set(requested_pages)
    else:
        pages_to_process = set(range(1, cached_doc.metadata.total_pages + 1))
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

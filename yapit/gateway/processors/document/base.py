from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.cache import SqliteCache
from yapit.gateway.config import Settings
from yapit.gateway.domain_models import CreditTransaction, DocumentProcessor, TransactionType, UserCredits


class ExtractedPage(BaseModel):
    """Single page extraction result."""

    markdown: str  # Full markdown with images/tables/latex


class DocumentExtractionResult(BaseModel):
    """Unified extraction result from any processor."""

    pages: dict[int, ExtractedPage]  # 1-indexed
    extraction_method: str
    # TODO: Consider adding extraction settings here if we support multiple configs


class CachedDocument(BaseModel):
    """Structure stored in cache for documents."""

    metadata: dict[str, Any]  # TODO this should be a proper model
    content: dict[str, Any] | None = (
        None  # Optional - for uploads  # TODO why is this a dict? I see we store the "url" here in the perepare from url endpoint... but why? Why not store the url in metadata? Shouldnt this jhust be for the pdf/image/b64/... content?
    )
    extraction: DocumentExtractionResult | None = None


class BaseDocumentProcessor(ABC):
    """Base class for all document processors."""

    def __init__(self, processor_slug: str, settings: Settings, **kwargs):
        self.processor_slug = processor_slug
        self.settings = settings

    @abstractmethod
    async def _extract(
        self,
        content: bytes,  # TODO this needs to accept both bytes and http url, as some processors e.g. just pass the url to the api, so we don't need to downlaod the content in all cases on our server... should prlly handle this by having two optional params... url and content, one of which has to be not None?
        content_type: str,
        pages: list[int] | None = None,
    ) -> DocumentExtractionResult:
        """Extract text from document. Always includes images if available."""
        pass

    async def process_with_billing(
        self,
        content: bytes,  # TODO this needs to accept both bytes and http url, as some processors e.g. just pass the url to the api, so we don't need to downlaod the content in all cases on our server... should prlly handle this by having two optional params... url and content, one of which has to be not None?
        content_type: str,
        user_id: str,
        cache_key: str,
        db: AsyncSession,
        cache: SqliteCache,
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
        existing_pages = set(cached_doc.extraction.pages.keys())
        total_pages = cached_doc.metadata.get("total_pages", 1)

        if pages:
            requested_pages = set(pages)
        else:
            requested_pages = set(range(1, total_pages + 1))

        missing_pages = requested_pages - existing_pages

        # If all pages are cached, return them
        if not missing_pages:
            return self._filter_pages(cached_doc.extraction, requested_pages)

        # Check credits
        user_credits = await db.get(UserCredits, user_id)
        if not user_credits:
            raise ValueError("User credits not found")

        credits_needed = len(missing_pages) * processor_model.credits_per_page
        if user_credits.balance < credits_needed:
            raise ValueError(f"Insufficient credits: need {credits_needed}, have {user_credits.balance}")

        # Process missing pages
        result = await self._extract(content, content_type, list(missing_pages))

        # Merge results
        cached_doc.extraction.pages.update(result.pages)

        # Update cache
        await cache.store(
            cache_key,
            cached_doc.model_dump_json().encode(),
            ttl_seconds=self.settings.document_cache_ttl_document,
        )

        # Bill for processed pages
        actual_credits = len(result.pages) * processor_model.credits_per_page
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
        credits: float,
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

"""Document extraction types, protocols, and config."""

import os
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from yapit.contracts import DetectedFigure
from yapit.gateway.domain_models import DocumentMetadata

# Dedicated thread pool for CPU-bound work (PDF processing, markdown parsing).
# Separate from the default pool so heavy work doesn't starve quick to_thread calls.
cpu_executor = ThreadPoolExecutor(max_workers=os.cpu_count() or 8, thread_name_prefix="cpu-bound")


class ExtractedPage(BaseModel):
    """Single page extraction result."""

    markdown: str
    images: list[str]


class DocumentExtractionResult(BaseModel):
    """Unified extraction result from any processor."""

    pages: dict[int, ExtractedPage]
    extraction_method: str
    failed_pages: list[int] = []


class CachedDocument(BaseModel):
    """Structure stored in cache for documents."""

    metadata: DocumentMetadata
    content: bytes | None = None
    extraction: DocumentExtractionResult | None = None

    model_config = ConfigDict(
        ser_json_bytes="base64",
        val_json_bytes="base64",
    )


@dataclass
class PageResult:
    """Result of processing a single page, yielded by extractors."""

    page_idx: int
    page: ExtractedPage | None
    input_tokens: int
    output_tokens: int
    thoughts_tokens: int
    is_fallback: bool
    cancelled: bool


@dataclass(frozen=True)
class ProcessorConfig:
    """Configuration for a document processor."""

    slug: str
    supported_mime_types: frozenset[str]
    max_pages: int
    max_file_size: int
    is_paid: bool
    output_token_multiplier: int
    extraction_cache_prefix: str | None
    supports_batch: bool = False

    def is_supported(self, mime_type: str) -> bool:
        base_type = mime_type.split(";")[0].strip()
        return base_type in self.supported_mime_types

    def extraction_cache_key(self, content_hash: str, page_idx: int) -> str:
        return f"{content_hash}:{self.extraction_cache_prefix}:{page_idx}"


@runtime_checkable
class Extractor(Protocol):
    """Protocol for AI document extraction backends (Gemini, OpenAI-compatible, etc.)."""

    def extract(
        self,
        content: bytes,
        content_type: str,
        content_hash: str,
        pages: list[int] | None = None,
        user_id: str | None = None,
        cancel_key: str | None = None,
    ) -> AsyncIterator[PageResult]: ...

    @property
    def model(self) -> str: ...


@runtime_checkable
class BatchExtractor(Extractor, Protocol):
    """Extractor that also supports async batch submission (e.g. Gemini Batch API)."""

    async def prepare_for_batch(
        self,
        content: bytes,
        content_hash: str,
        pages: list[int] | None = None,
    ) -> tuple[list, dict[int, list[str]]]: ...

    @property
    def client(self) -> Any: ...


@dataclass
class ProcessedDocument:
    """Result of processing extracted pages into a structured document."""

    extracted_text: str
    structured_content: str


@dataclass
class PreparedPage:
    """A page with YOLO detection complete, ready for LLM extraction."""

    page_idx: int
    page_bytes: bytes
    figures: list[DetectedFigure]
    figure_urls: list[str]


@dataclass
class ExtractedImage:
    data: bytes
    format: str
    width: int
    height: int


@dataclass
class PageEstimate:
    """Estimation result for a single page."""

    token_equiv: int
    text_chars: int
    is_raster: bool


@dataclass
class DocumentEstimate:
    """Estimation result for a document."""

    total_tokens: int
    total_text_chars: int
    num_pages: int
    raster_pages: int
    text_pages: int

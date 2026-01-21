"""Document extraction data models and configuration."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from yapit.gateway.constants import SUPPORTED_DOCUMENT_MIME_TYPES
from yapit.gateway.domain_models import DocumentMetadata


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


class ExtractFn(Protocol):
    def __call__(
        self,
        content: bytes,
        content_type: str,
        content_hash: str,
        pages: list[int] | None = None,
    ) -> AsyncIterator[PageResult]: ...

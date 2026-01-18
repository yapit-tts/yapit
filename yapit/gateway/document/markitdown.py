import io

from markitdown import MarkItDown

from yapit.gateway.cache import Cache
from yapit.gateway.document.base import (
    BaseDocumentProcessor,
    DocumentExtractionResult,
    ExtractedPage,
)


class MarkitdownProcessor(BaseDocumentProcessor):
    SUPPORTED_MIME_TYPES = {
        "text/html",
        "text/plain",
        "text/markdown",
        "text/x-markdown",
        "text/csv",
        "text/xml",
        "application/xml",
        "application/json",
        "application/rss+xml",
        "application/atom+xml",
        "application/zip",
        "application/epub+zip",
        "application/x-epub+zip",
        "application/pdf",
        "application/x-pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }

    def __init__(
        self,
        max_pages: int = 10000,
        max_file_size: int = 100 * 1024 * 1024,  # 100MB
        **kwargs,
    ):
        super().__init__(slug="markitdown", **kwargs)
        self._max_pages = max_pages
        self._max_file_size = max_file_size

    @property
    def _processor_supported_mime_types(self) -> set[str]:
        return self.SUPPORTED_MIME_TYPES

    @property
    def max_pages(self) -> int:
        return self._max_pages

    @property
    def max_file_size(self) -> int:
        return self._max_file_size

    async def _extract(
        self,
        content: bytes,
        content_type: str,
        content_hash: str,
        extraction_cache: Cache,
        pages: list[int] | None = None,
    ) -> DocumentExtractionResult:
        md = MarkItDown(enable_plugins=False)
        result = md.convert_stream(io.BytesIO(content))
        page = ExtractedPage(markdown=result.markdown, images=[])
        # Cache the single page (MarkItDown treats all content as one page)
        if self._extraction_key_prefix:
            cache_key = self._extraction_cache_key(content_hash, 0)
            await extraction_cache.store(cache_key, page.model_dump_json().encode())
        return DocumentExtractionResult(
            extraction_method=self._slug,
            pages={0: page},
        )

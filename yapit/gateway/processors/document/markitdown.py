import io

from markitdown import MarkItDown

from yapit.gateway.processors.document.base import BaseDocumentProcessor, DocumentExtractionResult, ExtractedPage


class MarkitdownProcessor(BaseDocumentProcessor):
    @property
    def _processor_supported_mime_types(self) -> set[str]:
        return {
            # default text formats
            "text/html",
            "text/plain",
            "text/csv",
            "text/xml",
            "application/xml",
            "application/json",
            "application/rss+xml",
            "application/atom+xml",
            "application/zip",
            "application/epub+zip",
            "application/x-epub+zip",
            # optional dependency [pdf]
            "application/pdf",
            "application/x-pdf",
            # optional dependency [docx]
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }

    @property
    def max_pages(self) -> int:
        return 10_000  # markitdown does not specify a limit

    @property
    def max_file_size(self) -> int:
        return self.settings.document_cache_max_file_size  # markitdown does not specify a limit

    async def _extract(
        self,
        content_type: str,
        url: str | None = None,
        content: bytes | None = None,
        pages: list[int] | None = None,
    ) -> DocumentExtractionResult:
        if not content:
            raise ValueError("Content must be provided")
        md = MarkItDown(enable_plugins=False)
        result = md.convert_stream(io.BytesIO(content))
        return DocumentExtractionResult(
            extraction_method=self.processor_slug,
            pages={1: ExtractedPage(markdown=result.markdown)},  # markitdown doesnt return pages
        )

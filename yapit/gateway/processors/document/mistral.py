import asyncio
import base64
import logging
import pprint

from mistralai import Mistral

from yapit.gateway.config import Settings
from yapit.gateway.processors.document.base import (
    BaseDocumentProcessor,
    DocumentExtractionResult,
    ExtractedPage,
)

log = logging.getLogger(__name__)


class MistralOCRProcessor(BaseDocumentProcessor):
    # TODO check which ones are actually supported... (tested so far: docx, pdf, png)
    IMAGE_MIME_TYPES = {
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/webp",
        "image/gif",
        "image/bmp",
        "image/tiff",
        "image/avif",
    }
    DOCUMENT_MIME_TYPES = {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.ms-powerpoint",
        "application/msword",
    }

    def __init__(self, slug: str, settings: Settings, model: str):
        super().__init__(slug, settings)

        if not settings.mistral_api_key:
            raise ValueError("MISTRAL_API_KEY is required for Mistral OCR processor")

        self._client = Mistral(api_key=settings.mistral_api_key)
        self._model = model

    @property
    def supported_mime_types(self) -> set[str]:
        return self.IMAGE_MIME_TYPES | self.DOCUMENT_MIME_TYPES

    @property
    def max_pages(self) -> int:
        return 1000

    @property
    def max_file_size(self) -> int:
        return 50 * 1024 * 1024

    async def _extract(
        self,
        url: str | None = None,
        content: bytes | None = None,
        content_type: str | None = None,
        pages: list[int] | None = None,
    ) -> DocumentExtractionResult:
        """Extract markdown with embedded images from document using Mistral OCR."""
        doc_url = self._get_document_type(content_type) if content_type else "document_url"

        request_params = {
            "model": self._model,
            "document": {
                "type": doc_url,
                doc_url: url if url else f"data:{content_type};base64,{base64.b64encode(content).decode('utf-8')}",
            },
            "include_image_base64": True,
            "pages": [p - 1 for p in pages] if pages else None,  # API uses 0-indexed
        }

        log.info(f"Calling Mistral OCR API with params:\n{pprint.pformat(request_params)}")
        response = await asyncio.to_thread(self._client.ocr.process, **request_params)
        return DocumentExtractionResult(
            pages={page.index + 1: ExtractedPage(markdown=page.markdown) for page in response.pages},  # 1-indexed pages
            extraction_method=self.processor_slug,
        )

    def _get_document_type(self, content_type: str) -> str:
        """Determine if content should be sent as image_url or document_url."""
        content_type_lower = content_type.lower()

        for mime in self.IMAGE_MIME_TYPES:
            if content_type_lower.startswith(mime):
                return "image_url"
        return "document_url"

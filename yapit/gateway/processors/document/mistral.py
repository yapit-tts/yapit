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


# TODO how are docs without pages billed?
# TODO what's the point of ocring text documents?
# TODO if we have the content already, is it better to pass the url (to save bandwidth) or the content (to not rely on external URLs, stability)?


class MistralOCRProcessor(BaseDocumentProcessor):
    IMAGE_MIME_TYPES = {
        "image/*",
    }
    DOCUMENT_MIME_TYPES = {
        "application/docbook+xml",
        "application/epub+zip",
        "application/pdf",
        "application/rtf",
        "application/vnd.oasis.opendocument.text",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/x-biblatex",
        "application/x-bibtex",
        "application/x-endnote+xml",
        "application/x-fictionbook+xml",
        "application/x-ipynb+json",
        "application/x-jats+xml",
        "application/x-latex",
        "application/x-opml+xml",
        "text/troff",
        "text/x-dokuwiki",
    }

    def __init__(self, slug: str, settings: Settings, model: str):
        super().__init__(slug, settings)

        if not settings.mistral_api_key:
            raise ValueError("MISTRAL_API_KEY is required for Mistral OCR processor")

        self._client = Mistral(api_key=settings.mistral_api_key)
        self._model = model

    @property
    def _processor_supported_mime_types(self) -> set[str]:
        return self.IMAGE_MIME_TYPES | self.DOCUMENT_MIME_TYPES

    @property
    def max_pages(self) -> int:
        return 1000

    @property
    def max_file_size(self) -> int:  # TODO use this to validate early
        return 50 * 1024 * 1024

    async def _extract(
        self,
        url: str | None = None,
        content: bytes | None = None,
        content_type: str | None = None,
        pages: list[int] | None = None,
    ) -> DocumentExtractionResult:
        doc_url = "image_url" if content_type and content_type.lower().startswith("image/") else "document_url"
        doc_content = url if url else f"data:{content_type};base64,{base64.b64encode(content).decode('utf-8')}"
        request_params = {
            "model": self._model,
            "document": {
                "type": doc_url,
                doc_url: doc_content,
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

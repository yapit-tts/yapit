import asyncio
import io
from pathlib import Path

import pymupdf
from google import genai
from google.genai import types
from pypdf import PdfReader

from yapit.gateway.processors.document.base import (
    BaseDocumentProcessor,
    DocumentExtractionResult,
    ExtractedPage,
)
from yapit.gateway.processors.document.extraction import (
    ExtractedImage,
    build_prompt_with_image_count,
    extract_images_from_page,
    extract_single_page_pdf,
    load_prompt,
    store_image,
    substitute_image_placeholders,
)

RESOLUTION_MAP = {
    "low": types.MediaResolution.MEDIA_RESOLUTION_LOW,
    "medium": types.MediaResolution.MEDIA_RESOLUTION_MEDIUM,
    "high": types.MediaResolution.MEDIA_RESOLUTION_HIGH,
}


class GeminiProcessor(BaseDocumentProcessor):
    SUPPORTED_MIME_TYPES = {
        "application/pdf",
        "image/*",
    }

    def __init__(
        self,
        model: str,
        resolution: str,
        max_concurrent: int,
        prompt_version: str,
        max_pages: int,
        max_file_size: int,
        **kwargs,
    ):
        super().__init__(**kwargs)

        if not self._settings.google_api_key:
            raise ValueError("GOOGLE_API_KEY is required for Gemini processor")

        self._client = genai.Client(api_key=self._settings.google_api_key)
        self._model = model
        self._resolution = RESOLUTION_MAP[resolution]
        self._max_concurrent = max_concurrent
        self._prompt = load_prompt(prompt_version)
        self._max_pages = max_pages
        self._max_file_size = max_file_size
        self._images_dir = Path(self._settings.images_dir)

    @property
    def _processor_supported_mime_types(self) -> set[str]:
        return self.SUPPORTED_MIME_TYPES

    @property
    def max_pages(self) -> int:
        return self._max_pages

    @property
    def max_file_size(self) -> int:
        return self._max_file_size

    @property
    def is_paid(self) -> bool:
        return True

    async def _extract(
        self,
        content: bytes,
        content_type: str,
        cache_key: str,
        pages: list[int] | None = None,
    ) -> DocumentExtractionResult:
        if content_type.startswith("image/"):
            return await self._extract_image(content, content_type)

        return await self._extract_pdf(content, pages, cache_key)

    async def _extract_image(self, content: bytes, content_type: str) -> DocumentExtractionResult:
        """Extract text from a single image."""
        config = types.GenerateContentConfig(media_resolution=self._resolution)

        response = await asyncio.to_thread(
            self._client.models.generate_content,
            model=self._model,
            contents=[
                types.Part.from_bytes(data=content, mime_type=content_type),
                self._prompt,
            ],
            config=config,
        )

        text = (response.text or "").strip()
        return DocumentExtractionResult(
            pages={0: ExtractedPage(markdown=text, images=[])},
            extraction_method=self._slug,
        )

    async def _extract_pdf(
        self,
        content: bytes,
        pages: list[int] | None,
        doc_hash: str,
    ) -> DocumentExtractionResult:
        """Extract text from PDF with parallel page processing."""
        pdf_reader = PdfReader(io.BytesIO(content))
        total_pages = len(pdf_reader.pages)

        pages_to_process = set(pages) if pages else set(range(total_pages))

        # Extract images from each page using PyMuPDF
        mupdf_doc = pymupdf.open(stream=content, filetype="pdf")
        page_images: dict[int, list[ExtractedImage]] = {}
        for page_idx in pages_to_process:
            page_images[page_idx] = extract_images_from_page(mupdf_doc, page_idx)
        mupdf_doc.close()

        # Store images and get URLs
        page_image_urls: dict[int, list[str]] = {}
        img_idx = 0
        for page_idx in sorted(pages_to_process):
            urls = []
            for img in page_images[page_idx]:
                url = store_image(img.data, img.format, self._images_dir, doc_hash, img_idx)
                urls.append(url)
                img_idx += 1
            page_image_urls[page_idx] = urls

        # Process pages with concurrency limit
        semaphore = asyncio.Semaphore(self._max_concurrent)
        tasks = [
            self._process_page(pdf_reader, page_idx, page_images[page_idx], page_image_urls[page_idx], semaphore)
            for page_idx in sorted(pages_to_process)
        ]
        results = await asyncio.gather(*tasks)

        return DocumentExtractionResult(
            pages={page_idx: page for page_idx, page in results},
            extraction_method=self._slug,
        )

    async def _process_page(
        self,
        pdf_reader: PdfReader,
        page_idx: int,
        images: list[ExtractedImage],
        image_urls: list[str],
        semaphore: asyncio.Semaphore,
    ) -> tuple[int, ExtractedPage]:
        """Process a single PDF page."""
        async with semaphore:
            page_bytes = extract_single_page_pdf(pdf_reader, page_idx)
            prompt = build_prompt_with_image_count(self._prompt, len(images))

            config = types.GenerateContentConfig(media_resolution=self._resolution)

            response = await asyncio.to_thread(
                self._client.models.generate_content,
                model=self._model,
                contents=[
                    types.Part.from_bytes(data=page_bytes, mime_type="application/pdf"),
                    prompt,
                ],
                config=config,
            )

            text = (response.text or "").strip()

            if image_urls:
                text = substitute_image_placeholders(text, image_urls)

            return page_idx, ExtractedPage(markdown=text, images=image_urls)

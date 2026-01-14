import asyncio
import io
import random
from pathlib import Path

import pymupdf
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from loguru import logger
from pypdf import PdfReader

from yapit.gateway.cache import Cache
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

# Retryable HTTP status codes (transient errors)
RETRYABLE_STATUS_CODES = {429, 500, 503, 504}
MAX_RETRIES = 3
BASE_DELAY_SECONDS = 1.0
MAX_DELAY_SECONDS = 8.0


class GeminiProcessor(BaseDocumentProcessor):
    SUPPORTED_MIME_TYPES = {
        "application/pdf",
        "image/*",
    }

    def __init__(
        self,
        model: str = "gemini-3-flash-preview",
        resolution: str = "high",
        max_concurrent: int = 20,
        prompt_version: str = "v1",
        max_pages: int = 10000,
        max_file_size: int = 100 * 1024 * 1024,  # 100MB
        **kwargs,
    ):
        super().__init__(slug="gemini", **kwargs)

        if not self._settings.google_api_key:
            raise ValueError("GOOGLE_API_KEY is required for Gemini processor")

        self._client = genai.Client(api_key=self._settings.google_api_key)
        self._model = model
        self._resolution_str = resolution
        self._resolution = RESOLUTION_MAP[resolution]
        self._max_concurrent = max_concurrent
        self._prompt_version = prompt_version
        self._prompt = load_prompt(prompt_version)
        self._max_pages = max_pages
        self._max_file_size = max_file_size
        self._images_dir = Path(self._settings.images_dir)

    @property
    def _processor_supported_mime_types(self) -> set[str]:
        return self.SUPPORTED_MIME_TYPES

    @property
    def _extraction_key_prefix(self) -> str:
        return f"{self._slug}:{self._resolution_str}:{self._prompt_version}"

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
        content_hash: str,
        extraction_cache: Cache,
        pages: list[int] | None = None,
    ) -> DocumentExtractionResult:
        if content_type.startswith("image/"):
            result = await self._extract_image(content, content_type)
            # Cache the single image page
            cache_key = self._extraction_cache_key(content_hash, 0)
            await extraction_cache.store(cache_key, result.pages[0].model_dump_json().encode())
            return result

        return await self._extract_pdf(content, pages, content_hash, extraction_cache)

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
        content_hash: str,
        extraction_cache: Cache,
    ) -> DocumentExtractionResult:
        """Extract text from PDF with parallel page processing, caching each page as it completes."""
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
        for page_idx in sorted(pages_to_process):
            urls = []
            for img_idx, img in enumerate(page_images[page_idx]):
                url = store_image(img.data, img.format, self._images_dir, content_hash, page_idx, img_idx)
                urls.append(url)
            page_image_urls[page_idx] = urls

        # Process pages with concurrency limit, caching each as it completes
        semaphore = asyncio.Semaphore(self._max_concurrent)

        async def process_and_cache(page_idx: int) -> tuple[int, ExtractedPage | None]:
            page_idx, page = await self._process_page(
                pdf_reader, page_idx, page_images[page_idx], page_image_urls[page_idx], semaphore
            )
            # Only cache successful extractions
            if page is not None:
                cache_key = self._extraction_cache_key(content_hash, page_idx)
                await extraction_cache.store(cache_key, page.model_dump_json().encode())
            return page_idx, page

        tasks = [process_and_cache(page_idx) for page_idx in sorted(pages_to_process)]
        results = await asyncio.gather(*tasks)

        # Separate successful and failed pages
        successful_pages = {page_idx: page for page_idx, page in results if page is not None}
        failed_pages = [page_idx for page_idx, page in results if page is None]

        if failed_pages:
            logger.error(f"Extraction completed with {len(failed_pages)} failed pages: {sorted(failed_pages)}")

        return DocumentExtractionResult(
            pages=successful_pages,
            extraction_method=self._slug,
            failed_pages=failed_pages,
        )

    async def _process_page(
        self,
        pdf_reader: PdfReader,
        page_idx: int,
        images: list[ExtractedImage],
        image_urls: list[str],
        semaphore: asyncio.Semaphore,
    ) -> tuple[int, ExtractedPage | None]:
        """Process a single PDF page with retry logic.

        Returns (page_idx, ExtractedPage) on success, (page_idx, None) on failure after all retries.
        """
        async with semaphore:
            page_bytes = extract_single_page_pdf(pdf_reader, page_idx)
            prompt = build_prompt_with_image_count(self._prompt, len(images))
            config = types.GenerateContentConfig(media_resolution=self._resolution)

            last_error: Exception | None = None
            for attempt in range(MAX_RETRIES):
                try:
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

                    if attempt > 0:
                        logger.info(f"Page {page_idx} succeeded after {attempt + 1} attempts")

                    return page_idx, ExtractedPage(markdown=text, images=image_urls)

                except genai_errors.APIError as e:
                    last_error = e
                    is_retryable = e.code in RETRYABLE_STATUS_CODES

                    if not is_retryable:
                        logger.error(f"Page {page_idx} failed with non-retryable error: {e.code} {e.message}")
                        return page_idx, None

                    if attempt < MAX_RETRIES - 1:
                        delay = min(BASE_DELAY_SECONDS * (2**attempt), MAX_DELAY_SECONDS)
                        jitter = random.uniform(0, delay * 0.5)
                        wait_time = delay + jitter
                        logger.warning(
                            f"Page {page_idx} attempt {attempt + 1}/{MAX_RETRIES} failed "
                            f"({e.code}), retrying in {wait_time:.1f}s"
                        )
                        await asyncio.sleep(wait_time)

                except Exception as e:
                    # Unexpected errors (network issues, etc.) - also retry
                    last_error = e
                    if attempt < MAX_RETRIES - 1:
                        delay = min(BASE_DELAY_SECONDS * (2**attempt), MAX_DELAY_SECONDS)
                        jitter = random.uniform(0, delay * 0.5)
                        wait_time = delay + jitter
                        logger.warning(
                            f"Page {page_idx} attempt {attempt + 1}/{MAX_RETRIES} failed "
                            f"with unexpected error: {e}, retrying in {wait_time:.1f}s"
                        )
                        await asyncio.sleep(wait_time)

            logger.error(f"Page {page_idx} failed after {MAX_RETRIES} attempts. Last error: {last_error}")
            return page_idx, None

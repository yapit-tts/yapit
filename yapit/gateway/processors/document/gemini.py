import asyncio
import io
import random
import time
from pathlib import Path

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
    DetectedFigure,
    build_figure_prompt,
    detect_figures,
    extract_single_page_pdf,
    load_prompt,
    render_page_as_image,
    store_figure,
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
        """Extract text from PDF with YOLO figure detection and parallel Gemini processing.

        Uses generator pattern: YOLO runs in background thread, Gemini requests fire
        as each page's figures are ready. This overlaps YOLO CPU work with Gemini latency.
        """
        start_time = time.monotonic()

        pdf_reader = PdfReader(io.BytesIO(content))
        total_pages = len(pdf_reader.pages)

        pages_to_process = sorted(set(pages) if pages else set(range(total_pages)))
        logger.info(f"Extraction: starting {len(pages_to_process)} pages (PDF has {total_pages} total)")

        # Queue for YOLO results: (page_idx, figures, figure_urls) or None as sentinel
        results_queue: asyncio.Queue[tuple[int, list[DetectedFigure], list[str]] | None] = asyncio.Queue()

        # Capture main event loop for thread-safe queue operations
        main_loop = asyncio.get_event_loop()

        # YOLO producer - runs in thread to not block event loop
        def yolo_producer():
            """Render pages, detect figures with YOLO, store crops, put results in queue."""
            total_pages = len(pages_to_process)

            for i, page_idx in enumerate(pages_to_process):
                try:
                    logger.info(f"YOLO: processing page {page_idx + 1} ({i + 1}/{total_pages})")

                    # Render page as image
                    page_image, width, height = render_page_as_image(content, page_idx)

                    # Detect figures with YOLO
                    figures = detect_figures(page_image, width, height)
                    logger.info(f"YOLO: page {page_idx + 1} - detected {len(figures)} figures")

                    # Store each figure and collect URLs
                    figure_urls = []
                    for fig_idx, figure in enumerate(figures):
                        url = store_figure(
                            figure, page_image, width, height, self._images_dir, content_hash, page_idx, fig_idx
                        )
                        figure_urls.append(url)

                    # Put result in queue (thread-safe via call_soon_threadsafe on MAIN loop)
                    main_loop.call_soon_threadsafe(
                        lambda p=page_idx, f=figures, u=figure_urls: results_queue.put_nowait((p, f, u))
                    )
                except Exception as e:
                    logger.error(f"YOLO detection failed for page {page_idx}: {e}")
                    # Put empty result so Gemini can still process the page (without figures)
                    main_loop.call_soon_threadsafe(lambda p=page_idx: results_queue.put_nowait((p, [], [])))

            logger.info(f"YOLO: completed all {total_pages} pages")
            # Signal completion
            main_loop.call_soon_threadsafe(lambda: results_queue.put_nowait(None))

        # Start YOLO producer in background thread
        main_loop.run_in_executor(None, yolo_producer)

        # Process Gemini requests as YOLO results arrive
        semaphore = asyncio.Semaphore(self._max_concurrent)
        tasks: list[asyncio.Task] = []

        async def process_and_cache(
            page_idx: int, figures: list[DetectedFigure], figure_urls: list[str]
        ) -> tuple[int, ExtractedPage | None]:
            page_idx, page = await self._process_page_with_figures(
                pdf_reader, page_idx, figures, figure_urls, semaphore
            )
            if page is not None:
                cache_key = self._extraction_cache_key(content_hash, page_idx)
                await extraction_cache.store(cache_key, page.model_dump_json().encode())
            return page_idx, page

        # Consume YOLO results and fire Gemini tasks
        while True:
            item = await results_queue.get()
            if item is None:  # Sentinel - YOLO producer done
                break
            page_idx, figures, figure_urls = item
            logger.info(f"Gemini: queuing page {page_idx + 1}")
            task = asyncio.create_task(process_and_cache(page_idx, figures, figure_urls))
            tasks.append(task)

        # Wait for all Gemini tasks to complete
        logger.info(f"Gemini: waiting for {len(tasks)} tasks to complete")
        results = await asyncio.gather(*tasks)

        # Separate successful and failed pages
        successful_pages = {page_idx: page for page_idx, page in results if page is not None}
        failed_pages = [page_idx for page_idx, page in results if page is None]

        elapsed = time.monotonic() - start_time
        if failed_pages:
            logger.error(f"Extraction completed with {len(failed_pages)} failed pages: {sorted(failed_pages)}")
        logger.info(f"Extraction: completed {len(successful_pages)}/{len(pages_to_process)} pages in {elapsed:.1f}s")

        return DocumentExtractionResult(
            pages=successful_pages,
            extraction_method=self._slug,
            failed_pages=failed_pages,
        )

    async def _process_page_with_figures(
        self,
        pdf_reader: PdfReader,
        page_idx: int,
        figures: list[DetectedFigure],
        figure_urls: list[str],
        semaphore: asyncio.Semaphore,
    ) -> tuple[int, ExtractedPage | None]:
        """Process a single PDF page with YOLO-detected figures.

        Returns (page_idx, ExtractedPage) on success, (page_idx, None) on failure after all retries.
        """
        async with semaphore:
            page_bytes = extract_single_page_pdf(pdf_reader, page_idx)
            prompt = build_figure_prompt(self._prompt, figures)
            config = types.GenerateContentConfig(media_resolution=self._resolution)

            last_error: Exception | None = None
            for attempt in range(MAX_RETRIES):
                try:
                    logger.info(f"Gemini: calling API for page {page_idx + 1}")
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
                    if figure_urls:
                        text = substitute_image_placeholders(text, figure_urls)

                    if attempt > 0:
                        logger.info(f"Gemini: page {page_idx + 1} succeeded after {attempt + 1} attempts")
                    else:
                        logger.info(f"Gemini: page {page_idx + 1} completed")

                    return page_idx, ExtractedPage(markdown=text, images=figure_urls)

                except genai_errors.APIError as e:
                    last_error = e
                    is_retryable = e.code in RETRYABLE_STATUS_CODES

                    if not is_retryable:
                        logger.error(
                            f"Gemini: page {page_idx + 1} failed with non-retryable error: {e.code} {e.message}"
                        )
                        return page_idx, None

                    if attempt < MAX_RETRIES - 1:
                        delay = min(BASE_DELAY_SECONDS * (2**attempt), MAX_DELAY_SECONDS)
                        jitter = random.uniform(0, delay * 0.5)
                        wait_time = delay + jitter
                        logger.warning(
                            f"Gemini: page {page_idx + 1} attempt {attempt + 1}/{MAX_RETRIES} failed "
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
                            f"Gemini: page {page_idx + 1} attempt {attempt + 1}/{MAX_RETRIES} failed "
                            f"with unexpected error: {e}, retrying in {wait_time:.1f}s"
                        )
                        await asyncio.sleep(wait_time)

            logger.error(f"Gemini: page {page_idx + 1} failed after {MAX_RETRIES} attempts. Last error: {last_error}")
            return page_idx, None

"""Background task that polls batch jobs for completion and processes results."""

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timezone

from google import genai
from google.genai import types
from loguru import logger
from redis.asyncio import Redis
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.cache import Cache
from yapit.gateway.config import Settings
from yapit.gateway.document.batch import (
    BatchJobInfo,
    BatchJobStatus,
    get_batch_results,
    list_pending_batch_jobs,
    poll_batch_job,
    save_batch_job,
)
from yapit.gateway.document.extraction import substitute_image_placeholders
from yapit.gateway.document.processing import (
    ExtractedPage,
    create_document_with_blocks,
    process_pages_to_document,
)
from yapit.gateway.domain_models import Document, DocumentMetadata, UsageType
from yapit.gateway.metrics import log_event
from yapit.gateway.reservations import release_reservation
from yapit.gateway.usage import record_usage

POLL_INTERVAL_SECONDS = 15


async def process_batch_completion(
    client: genai.Client,
    job: BatchJobInfo,
    batch_job: types.BatchJob,
    redis: Redis,
    db: AsyncSession,
    extraction_cache: Cache,
    extraction_cache_prefix: str,
    output_token_multiplier: int,
) -> tuple[dict[int, ExtractedPage], list[int]]:
    """Process results from a completed batch job.

    Returns:
        (pages dict, failed_page_indices list)
    """
    start_time = time.monotonic()
    results = await get_batch_results(client, batch_job)

    pages: dict[int, ExtractedPage] = {}
    failed_pages: list[int] = []
    total_input_tokens = 0
    total_output_tokens = 0
    total_thoughts_tokens = 0

    try:
        for result in results:
            if result.key is None:
                logger.warning("Batch result missing key, skipping")
                continue

            page_idx = int(result.key.replace("page_", ""))

            if result.error:
                logger.warning(f"Batch page {page_idx} failed: {result.error}")
                failed_pages.append(page_idx)
                continue

            if result.response is None:
                failed_pages.append(page_idx)
                continue

            text = (result.response.text or "").strip()

            figure_urls = job.figure_urls_by_page.get(page_idx, [])
            if figure_urls:
                text = substitute_image_placeholders(text, figure_urls)

            pages[page_idx] = ExtractedPage(markdown=text, images=figure_urls)

            usage = result.response.usage_metadata
            if usage:
                input_tokens = usage.prompt_token_count or 0
                output_tokens = usage.candidates_token_count or 0
                thoughts_tokens = usage.thoughts_token_count or 0

                total_input_tokens += input_tokens
                total_output_tokens += output_tokens
                total_thoughts_tokens += thoughts_tokens

                token_equiv = input_tokens + (output_tokens + thoughts_tokens) * output_token_multiplier
                await record_usage(
                    user_id=job.user_id,
                    usage_type=UsageType.ocr_tokens,
                    amount=token_equiv,
                    db=db,
                    reference_id=job.content_hash,
                    description=f"Batch page {page_idx + 1} extraction",
                    details={
                        "page_idx": page_idx,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "thoughts_tokens": thoughts_tokens,
                        "token_equiv": token_equiv,
                        "batch_job": job.job_name,
                    },
                )

            cache_key = f"{job.content_hash}:{extraction_cache_prefix}:{page_idx}"
            await extraction_cache.store(cache_key, pages[page_idx].model_dump_json().encode())
    finally:
        await release_reservation(redis, job.user_id, job.content_hash)

    result_processing_ms = int((time.monotonic() - start_time) * 1000)
    submitted_at = datetime.fromisoformat(job.submitted_at)
    total_duration_ms = int((datetime.now(timezone.utc) - submitted_at).total_seconds() * 1000)

    await log_event(
        "batch_job_complete",
        user_id=job.user_id,
        duration_ms=total_duration_ms,
        data={
            "job_name": job.job_name,
            "content_hash": job.content_hash,
            "total_pages": job.total_pages,
            "succeeded_pages": len(pages),
            "failed_pages": len(failed_pages),
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_thoughts_tokens": total_thoughts_tokens,
            "result_processing_ms": result_processing_ms,
        },
    )

    logger.info(
        f"Batch job {job.job_name} completed: {len(pages)} succeeded, {len(failed_pages)} failed, "
        f"total {total_duration_ms // 1000}s, tokens: {total_input_tokens}in/{total_output_tokens}out/{total_thoughts_tokens}think"
    )

    return pages, failed_pages


async def create_document_from_batch(
    job: BatchJobInfo,
    pages: dict[int, ExtractedPage],
    db: AsyncSession,
    settings: Settings,
) -> Document:
    """Create a Document from batch extraction results."""
    processed = process_pages_to_document(pages, settings)

    metadata = DocumentMetadata(
        content_type=job.content_type,
        total_pages=job.total_pages,
        title=job.title,
        url=None,
        file_name=None,
        file_size=job.file_size,
    )

    doc = await create_document_with_blocks(
        db=db,
        user_id=job.user_id,
        title=job.title,
        original_text=processed.extracted_text,
        structured_content=processed.structured_content,
        metadata=metadata,
        extraction_method="gemini",
        text_blocks=processed.text_blocks,
        is_public=False,
        content_hash=job.content_hash,
    )

    logger.info(f"Created document {doc.id} from batch job {job.job_name}")
    return doc


async def handle_batch_failure(
    job: BatchJobInfo,
    redis: Redis,
    error: str | None = None,
) -> None:
    """Handle a failed/expired batch job."""
    await release_reservation(redis, job.user_id, job.content_hash)

    job.error = error or f"Job ended with status: {job.status}"
    await save_batch_job(redis, job)

    await log_event(
        "batch_job_failed",
        user_id=job.user_id,
        data={
            "job_name": job.job_name,
            "content_hash": job.content_hash,
            "status": job.status.value,
            "error": job.error,
        },
    )

    logger.error(f"Batch job {job.job_name} failed: {job.error}")


class BatchPoller:
    """Background service that polls batch jobs and processes completions."""

    def __init__(
        self,
        gemini_client: genai.Client,
        redis: Redis,
        get_db_session: Callable[[], AsyncIterator[AsyncSession]],
        extraction_cache: Cache,
        settings: Settings,
        extraction_cache_prefix: str,
        output_token_multiplier: int = 6,
    ):
        self._client = gemini_client
        self._redis = redis
        self._get_db_session = get_db_session
        self._extraction_cache = extraction_cache
        self._settings = settings
        self._extraction_cache_prefix = extraction_cache_prefix
        self._output_token_multiplier = output_token_multiplier
        self._running = False
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("Batch poller started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Batch poller stopped")

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                jobs = await list_pending_batch_jobs(self._redis)

                for job in jobs:
                    if not self._running:
                        break
                    try:
                        await self._poll_and_handle_job(job)
                    except Exception as e:
                        logger.error(f"Error polling batch job {job.job_name}: {e}")

                await asyncio.sleep(POLL_INTERVAL_SECONDS)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Batch poller error: {e}")
                await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _poll_and_handle_job(self, job: BatchJobInfo) -> None:
        job, batch_job = await poll_batch_job(self._client, self._redis, job)

        if job.status == BatchJobStatus.SUCCEEDED:
            async for db in self._get_db_session():
                pages, failed_pages = await process_batch_completion(
                    client=self._client,
                    job=job,
                    batch_job=batch_job,
                    redis=self._redis,
                    db=db,
                    extraction_cache=self._extraction_cache,
                    extraction_cache_prefix=self._extraction_cache_prefix,
                    output_token_multiplier=self._output_token_multiplier,
                )

                if pages:
                    doc = await create_document_from_batch(job, pages, db, self._settings)
                    job.document_id = str(doc.id)
                    await save_batch_job(self._redis, job)
                    # Job stays in Redis with SUCCEEDED + document_id for frontend to poll
                    # TTL will clean it up eventually

        elif job.status in (BatchJobStatus.FAILED, BatchJobStatus.EXPIRED):
            await handle_batch_failure(job, self._redis)

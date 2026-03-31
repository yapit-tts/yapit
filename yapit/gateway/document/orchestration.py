"""Document extraction orchestration: billing, caching, and page assembly."""

import asyncio
import re
from collections.abc import AsyncIterator

from loguru import logger
from redis.asyncio import Redis

from yapit.gateway.cache import Cache
from yapit.gateway.db import create_session
from yapit.gateway.document.pdf import PER_PAGE_TOLERANCE, estimate_document_tokens
from yapit.gateway.document.types import (
    DocumentExtractionResult,
    ExtractedPage,
    PageResult,
    ProcessedDocument,
    ProcessorConfig,
    cpu_executor,
)
from yapit.gateway.domain_models import UsageType
from yapit.gateway.exceptions import ValidationError
from yapit.gateway.markdown import parse_markdown
from yapit.gateway.markdown.transformer import DocumentTransformer
from yapit.gateway.metrics import log_event
from yapit.gateway.reservations import create_reservation, release_reservation
from yapit.gateway.storage import ImageStorage
from yapit.gateway.usage import check_usage_limit, record_usage


async def process_with_billing(
    config: ProcessorConfig,
    extractor: AsyncIterator[PageResult],
    user_id: str,
    content: bytes,
    content_type: str,
    content_hash: str,
    total_pages: int,
    extraction_cache: Cache,
    image_storage: ImageStorage,
    redis: Redis,
    billing_enabled: bool,
    file_size: int | None = None,
    pages: list[int] | None = None,
    prompt_hash: str | None = None,
) -> DocumentExtractionResult:
    """Orchestrate document extraction with validation, caching, and billing.

    1. Validate content type and limits
    2. Check extraction cache for already-processed pages
    3. Estimate tokens, check usage limit, create reservation (paid processors)
    4. Extract uncached pages, caching each as it completes
    5. Bill all successful pages
    6. Release reservation and return merged result (cached + fresh pages)
    """
    # 1. Validate
    if not config.is_supported(content_type):
        raise ValidationError(
            f"Unsupported content type: {content_type}. Supported: {', '.join(sorted(config.supported_mime_types))}"
        )
    if total_pages > config.max_pages:
        raise ValidationError(
            f"Document has {total_pages} pages, but this processor supports a maximum of {config.max_pages} pages."
        )
    if file_size and file_size > config.max_file_size:
        raise ValidationError(
            f"Document size {file_size} bytes exceeds the maximum allowed size of {config.max_file_size} bytes."
        )

    # 2. Check extraction cache
    requested_pages = set(pages) if pages else set(range(total_pages))
    cached_pages: dict[int, ExtractedPage] = {}
    uncached_pages: set[int] = set()

    if config.extraction_cache_prefix:
        cache_key_map = {config.extraction_cache_key(content_hash, idx, prompt_hash): idx for idx in requested_pages}
        cached_data = await extraction_cache.batch_retrieve(list(cache_key_map.keys()))
        for key, data in cached_data.items():
            page_idx = cache_key_map[key]
            cached_pages[page_idx] = ExtractedPage.model_validate_json(data)
            await log_event("extraction_cache_hit", processor_slug=config.slug, page_idx=page_idx, user_id=user_id)
        uncached_pages = requested_pages - set(cached_pages.keys())

        has_cached_images = any(page.images for page in cached_pages.values())
        if has_cached_images and not await image_storage.exists(content_hash):
            logger.info(f"Images missing for {content_hash}, invalidating extraction cache")
            cached_pages = {}
            uncached_pages = requested_pages
    else:
        uncached_pages = requested_pages

    if not uncached_pages:
        return DocumentExtractionResult(pages=cached_pages, extraction_method=config.slug)

    # 3. Check usage limit and create reservation (paid processors only)
    estimated_tokens = 0
    if config.is_paid:
        estimate = await asyncio.get_running_loop().run_in_executor(
            cpu_executor,
            estimate_document_tokens,
            content,
            content_type,
            config.output_token_multiplier,
            list(uncached_pages),
        )
        tolerance = PER_PAGE_TOLERANCE * estimate.num_pages
        amount_to_check = max(0, estimate.total_tokens - tolerance)
        estimated_tokens = estimate.total_tokens

        await log_event(
            "extraction_estimate",
            processor_slug=config.slug,
            user_id=user_id,
            data={
                "content_hash": content_hash,
                "num_pages": estimate.num_pages,
                "text_pages": estimate.text_pages,
                "raster_pages": estimate.raster_pages,
                "total_text_chars": estimate.total_text_chars,
                "estimated_tokens": estimate.total_tokens,
                "tolerance": tolerance,
                "amount_checked": amount_to_check,
            },
        )

        async with create_session() as db:
            await check_usage_limit(
                user_id,
                UsageType.ocr_tokens,
                amount_to_check,
                db,
                billing_enabled=billing_enabled,
                redis=redis,
            )

        await create_reservation(redis, user_id, content_hash, estimated_tokens)

    # 4. Extract and cache pages
    fresh_pages: dict[int, ExtractedPage] = {}
    failed_pages: list[int] = []
    billing_records: list[dict] = []

    try:
        async for result in extractor:
            if result.cancelled:
                logger.info(f"Page {result.page_idx + 1} was cancelled")
                continue

            if result.page is None:
                failed_pages.append(result.page_idx)
                continue

            fresh_pages[result.page_idx] = result.page

            if config.extraction_cache_prefix:
                cache_key = config.extraction_cache_key(content_hash, result.page_idx, prompt_hash)
                await extraction_cache.store(cache_key, result.page.model_dump_json().encode())

            if config.is_paid:
                token_equiv = (
                    result.input_tokens
                    + (result.output_tokens + result.thoughts_tokens) * config.output_token_multiplier
                )
                billing_records.append(
                    {
                        "amount": token_equiv,
                        "description": f"Page {result.page_idx + 1} extraction with {config.slug}",
                        "details": {
                            "processor": config.slug,
                            "page_idx": result.page_idx,
                            "input_tokens": result.input_tokens,
                            "output_tokens": result.output_tokens,
                            "thoughts_tokens": result.thoughts_tokens,
                            "token_equiv": token_equiv,
                            "is_fallback": result.is_fallback,
                        },
                    }
                )

        # 5. Bill all successful pages in one short DB session
        if billing_records:
            async with create_session() as db:
                for record in billing_records:
                    await record_usage(
                        user_id=user_id,
                        usage_type=UsageType.ocr_tokens,
                        amount=record["amount"],
                        db=db,
                        reference_id=content_hash,
                        description=record["description"],
                        details=record["details"],
                        commit=False,
                    )
                await db.commit()
    finally:
        if config.is_paid and estimated_tokens > 0:
            await release_reservation(redis, user_id, content_hash)

    # 6. Merge cached + fresh, sort by page index
    all_pages = {**cached_pages, **fresh_pages}
    sorted_pages = dict(sorted(all_pages.items()))

    return DocumentExtractionResult(
        pages=sorted_pages,
        extraction_method=config.slug,
        failed_pages=failed_pages,
    )


def process_pages_to_document(
    pages: dict[int, ExtractedPage],
    transformer: DocumentTransformer,
) -> ProcessedDocument:
    """Transform extracted pages into structured document content."""
    page_markdowns = {idx: page.markdown for idx, page in pages.items()}
    deduped_markdowns = deduplicate_footnotes(page_markdowns)
    extracted_text = "\n\n".join(deduped_markdowns[idx] for idx in sorted(deduped_markdowns.keys()))

    ast = parse_markdown(extracted_text)
    structured_doc = transformer.transform(ast)

    text_blocks = structured_doc.get_audio_blocks()
    soft_max = transformer.splitter.soft_max
    oversized = [(i, len(t)) for i, t in enumerate(text_blocks) if len(t) > soft_max]
    if oversized:
        logger.warning(
            "Blocks exceed soft_max ({max}): {blocks}",
            max=soft_max,
            blocks=", ".join(f"block[{i}]={n} chars" for i, n in oversized),
        )

    return ProcessedDocument(
        extracted_text=extracted_text,
        structured_content=structured_doc.model_dump_json(),
    )


def stitch_pages(page_texts: list[str]) -> str:
    """Stitch page outputs into coherent document.

    Heuristic: if page N ends without sentence-ending punctuation and page N+1
    starts with lowercase, join with space (likely continuation). Otherwise
    join with double newline.
    """
    if not page_texts:
        return ""

    sentence_enders = re.compile(r'[.!?:;"\'\)\]]$')
    starts_lowercase = re.compile(r"^[a-z]")

    result = [page_texts[0]]

    for i in range(1, len(page_texts)):
        prev_text = page_texts[i - 1].rstrip()
        curr_text = page_texts[i].lstrip()

        if prev_text and curr_text:
            prev_ends_sentence = bool(sentence_enders.search(prev_text))
            curr_starts_lower = bool(starts_lowercase.match(curr_text))

            if not prev_ends_sentence and curr_starts_lower:
                result.append(" ")
            else:
                result.append("\n\n")
        else:
            result.append("\n\n")

        result.append(curr_text)

    return "".join(result)


_FOOTNOTE_REF_PATTERN = re.compile(r"\[\^([^\]]+)\](?!:)")
_FOOTNOTE_DEF_PATTERN = re.compile(r"^\[\^([^\]]+)\]:", re.MULTILINE)


def deduplicate_footnotes(pages: dict[int, str]) -> dict[int, str]:
    """Deduplicate footnote labels across pages to prevent collisions."""
    if len(pages) <= 1:
        return pages

    page_def_labels: dict[int, set[str]] = {}
    for page_idx, markdown in pages.items():
        page_def_labels[page_idx] = set(_FOOTNOTE_DEF_PATTERN.findall(markdown))

    label_pages: dict[str, list[int]] = {}
    for page_idx, labels in page_def_labels.items():
        for label in labels:
            label_pages.setdefault(label, []).append(page_idx)

    colliding_labels = {label for label, pgs in label_pages.items() if len(pgs) > 1}
    if not colliding_labels:
        return pages

    result: dict[int, str] = {}
    for page_idx, markdown in pages.items():
        to_rename = page_def_labels.get(page_idx, set()) & colliding_labels
        if not to_rename:
            result[page_idx] = markdown
            continue

        renamed = markdown
        for label in to_rename:
            new_label = f"p{page_idx}-{label}"
            renamed = re.sub(
                rf"\[\^{re.escape(label)}\](?!:)",
                f"[^{new_label}]",
                renamed,
            )
            renamed = re.sub(
                rf"^\[\^{re.escape(label)}\]:",
                f"[^{new_label}]:",
                renamed,
                flags=re.MULTILINE,
            )
        result[page_idx] = renamed

    return result

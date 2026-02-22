"""One-shot cache warming and pinning for voice previews and showcase documents.

Pre-synthesizes audio so preview sentences and showcase docs are cached and
playable for free (cached audio skips billing). Pins warmed entries so LRU
eviction never touches them.

Run manually when voices or showcase content changes:
    python -m yapit.gateway.warm_cache
"""

import asyncio
import sys
import uuid
from dataclasses import dataclass, field
from typing import Literal

import redis.asyncio as aioredis
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy.orm import selectinload
from sqlmodel import col, select

from yapit.gateway.cache import Cache
from yapit.gateway.config import Settings
from yapit.gateway.db import close_db, create_session
from yapit.gateway.deps import create_cache
from yapit.gateway.domain_models import BlockVariant, Document, TTSModel, Voice
from yapit.gateway.synthesis import CachedResult, QueuedResult, synthesize_and_wait

PREVIEW_DOCUMENT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

PREVIEW_SENTENCES = [
    "Hello, this is a sample of my voice.",
    "The quick brown fox jumps over the lazy dog.",
    "I can read documents, articles, and research papers.",
    "Sometimes I wonder what it would be like to have a body.",
    "Breaking news: scientists discover that coffee is, in fact, essential.",
]


@dataclass
class ShowcaseDoc:
    id: uuid.UUID
    # Per-model voice filter: "all" warms every active voice, "english" only lang.startswith("en")
    voice_filter: dict[str, Literal["all", "english", "skip"]] = field(default_factory=dict)


SHOWCASE_DOCS = [
    ShowcaseDoc(
        id=uuid.UUID("1c185db2-cdd7-4de4-9016-c1ff6abe4cd9"),  # File Over App
        voice_filter={},  # empty = "all" for every model
    ),
    ShowcaseDoc(
        id=uuid.UUID("3bde213b-3a5a-465f-9198-be65430b699e"),  # Attention Is All You Need
        voice_filter={"inworld-1.5": "english", "inworld-1.5-max": "english"},
    ),
]


@dataclass
class WarmingStats:
    cached: int = 0
    synthesized: int = 0
    failed: int = 0


def filter_voices(
    model: TTSModel,
    voice_filter: dict[str, Literal["all", "english", "skip"]],
) -> list[Voice]:
    strategy = voice_filter.get(model.slug, "all")
    if strategy == "skip":
        return []
    active = [v for v in model.voices if v.is_active]
    if strategy == "english":
        active = [v for v in active if v.lang and v.lang.startswith("en")]
    return active


async def warm_texts(
    settings: Settings,
    redis_client: Redis,
    cache: Cache,
    model: TTSModel,
    voices: list[Voice],
    texts: list[str],
    document_id: uuid.UUID,
    stats: WarmingStats,
) -> list[str]:
    """Synthesize texts for each voice, return variant hashes of all successful entries."""
    hashes: list[str] = []
    for vi, voice in enumerate(voices, 1):
        voice_cached = voice_synthesized = voice_failed = 0

        # Check which entries already exist so we can report accurate counts
        text_hashes = [BlockVariant.get_hash(text, model.slug, voice.slug, voice.parameters) for text in texts]
        already_cached = await cache.batch_exists(text_hashes)

        for idx, (text, h) in enumerate(zip(texts, text_hashes)):
            if h in already_cached:
                stats.cached += 1
                voice_cached += 1
                hashes.append(h)
                continue

            async for db in create_session(settings):
                result = await synthesize_and_wait(
                    db=db,
                    redis=redis_client,
                    cache=cache,
                    user_id="cache-warmer",
                    text=text,
                    model=model,
                    voice=voice,
                    billing_enabled=False,
                    document_id=document_id,
                    block_idx=idx,
                    timeout_seconds=30.0,
                    poll_interval=0.2,
                )
                break

            if isinstance(result, (CachedResult, QueuedResult)):
                stats.synthesized += 1
                voice_synthesized += 1
                hashes.append(h)
            else:
                stats.failed += 1
                voice_failed += 1
                logger.bind(model_slug=model.slug, voice_slug=voice.slug, block_idx=idx).warning(
                    f"Warming failed: {result.error}"
                )

        logger.info(
            f"  {voice.slug} ({vi}/{len(voices)}): "
            f"{voice_synthesized} synthesized, {voice_cached} cached, {voice_failed} failed"
        )
    return hashes


async def run_warming(cache: Cache, redis_client: Redis, settings: Settings) -> WarmingStats:
    """Run the full warming cycle: synthesize missing entries, then pin all warmed keys."""
    async for db in create_session(settings):
        models = (
            await db.exec(
                select(TTSModel).where(col(TTSModel.is_active).is_(True)).options(selectinload(TTSModel.voices))  # type: ignore[arg-type]
            )
        ).all()
        break

    stats = WarmingStats()
    all_hashes: list[str] = []

    # --- Voice previews ---
    total_voices = sum(len([v for v in m.voices if v.is_active]) for m in models)
    logger.info(
        f"Voice previews: {len(models)} models, {total_voices} voices, {total_voices * len(PREVIEW_SENTENCES)} requests"
    )

    for model in models:
        active = [v for v in model.voices if v.is_active]
        logger.info(f"{model.slug}: {len(active)} voices")
        hashes = await warm_texts(
            settings, redis_client, cache, model, active, PREVIEW_SENTENCES, PREVIEW_DOCUMENT_ID, stats
        )
        all_hashes.extend(hashes)

    # --- Showcase documents ---
    for showcase in SHOWCASE_DOCS:
        async for db in create_session(settings):
            doc = (
                await db.exec(
                    select(Document).where(Document.id == showcase.id).options(selectinload(Document.blocks))  # type: ignore[arg-type]
                )
            ).first()
            break

        if doc is None:
            logger.warning(f"Showcase doc {showcase.id} not found, skipping")
            continue

        block_texts = [b.text for b in sorted(doc.blocks, key=lambda b: b.idx)]
        logger.info(f"Showcase '{doc.title}': {len(block_texts)} blocks")

        for model in models:
            voices = filter_voices(model, showcase.voice_filter)
            logger.info(f"  {model.slug}: {len(voices)} voices")
            hashes = await warm_texts(settings, redis_client, cache, model, voices, block_texts, showcase.id, stats)
            all_hashes.extend(hashes)

    # --- Pin all warmed entries ---
    pinned = await cache.pin(all_hashes)
    logger.info(
        f"Cache warming done: {stats.cached} cached, {stats.synthesized} synthesized, "
        f"{stats.failed} failed, {pinned} newly pinned"
    )
    return stats


async def main() -> int:
    """Standalone entry point for manual one-off warming."""
    settings = Settings()  # type: ignore[call-arg]
    redis_client = await aioredis.from_url(settings.redis_url, decode_responses=False)
    cache = create_cache(settings.audio_cache_type, settings.audio_cache_config)

    try:
        stats = await run_warming(cache, redis_client, settings)
        return 0 if stats.failed == 0 else 1
    finally:
        await cache.close()
        await redis_client.aclose()
        await close_db()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

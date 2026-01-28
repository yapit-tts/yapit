"""Cache warming script for voice previews.

Run inside the gateway container:
    python -m yapit.gateway.warm_cache

Or via systemd timer on VPS.
"""

import asyncio
import sys
import uuid
from dataclasses import dataclass

import redis.asyncio as redis
from loguru import logger
from sqlalchemy.orm import selectinload
from sqlmodel import col, select

from yapit.gateway.config import Settings
from yapit.gateway.db import close_db, create_session
from yapit.gateway.deps import create_cache
from yapit.gateway.domain_models import TTSModel
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
class WarmingStats:
    cached: int = 0
    synthesized: int = 0
    failed: int = 0


async def warm_model_voices(
    settings: Settings,
    redis_client: redis.Redis,
    model: TTSModel,
    stats: WarmingStats,
) -> None:
    """Warm all voice previews for a single model."""
    cache = create_cache(settings.audio_cache_type, settings.audio_cache_config)
    active_voices = [v for v in model.voices if v.is_active]

    for voice in active_voices:
        for idx, sentence in enumerate(PREVIEW_SENTENCES):
            async for db in create_session(settings):
                result = await synthesize_and_wait(
                    db=db,
                    redis=redis_client,
                    cache=cache,
                    user_id="cache-warmer",
                    text=sentence,
                    model=model,
                    voice=voice,
                    billing_enabled=False,
                    document_id=PREVIEW_DOCUMENT_ID,
                    block_idx=idx,
                    timeout_seconds=30.0,
                    poll_interval=0.2,
                )
                break

            if isinstance(result, CachedResult):
                stats.cached += 1
            elif isinstance(result, QueuedResult):
                stats.synthesized += 1
            else:
                stats.failed += 1
                logger.warning(f"Failed {model.slug}/{voice.slug}[{idx}]: {result.error}")

        logger.info(f"  {voice.slug}: done")


async def main() -> int:
    settings = Settings()  # type: ignore[call-arg]
    redis_client = await redis.from_url(settings.redis_url, decode_responses=False)

    try:
        async for db in create_session(settings):
            models = (
                await db.exec(
                    select(TTSModel).where(col(TTSModel.is_active).is_(True)).options(selectinload(TTSModel.voices))  # type: ignore[arg-type]
                )
            ).all()
            break

        total_voices = sum(len([v for v in m.voices if v.is_active]) for m in models)
        total_requests = total_voices * len(PREVIEW_SENTENCES)
        logger.info(f"Warming {len(models)} models, {total_voices} voices, {total_requests} total requests")

        stats = WarmingStats()

        for model in models:
            active_count = len([v for v in model.voices if v.is_active])
            logger.info(f"{model.slug}: {active_count} voices")
            await warm_model_voices(settings, redis_client, model, stats)

        logger.info(f"Done: {stats.cached} cached, {stats.synthesized} synthesized, {stats.failed} failed")
        return 0 if stats.failed == 0 else 1

    finally:
        await redis_client.aclose()
        await close_db()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

"""Database seeding for models, voices, plans, etc."""

import json
from pathlib import Path

import httpx
from loguru import logger
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import col, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.config import Settings
from yapit.gateway.domain_models import Plan, PlanTier, TTSModel, Voice

INWORLD_VOICES_JSON = Path(__file__).parent.parent / "data/inworld/voices.json"
KOKORO_VOICES_JSON = Path(__file__).parent.parent / "workers/kokoro/voices.json"


def _load_inworld_voices() -> list[dict]:
    data = json.loads(INWORLD_VOICES_JSON.read_text())
    return [
        {
            "slug": v["voiceId"].lower(),
            "name": v["displayName"],
            "lang": v["languages"][0] if v.get("languages") else "en",
            "description": v.get("description", ""),
            "parameters": {"voice_id": v["voiceId"]},
        }
        for v in data.get("voices", [])
    ]


def create_models() -> list[TTSModel]:
    """Create TTS models with voices. Used for fresh DB seeding only."""
    kokoro = TTSModel(slug="kokoro", name="Kokoro")
    for v in json.loads(KOKORO_VOICES_JSON.read_text()):
        kokoro.voices.append(
            Voice(  # type: ignore[missing-argument]
                slug=v["index"],
                name=v["name"],
                lang=v["language"],
                description=f"Quality grade {v['overallGrade']}",
                parameters={"voice": v["index"], "speed": 1.0},
            )
        )

    inworld = TTSModel(slug="inworld-1.5", name="Inworld TTS-1.5")
    inworld_max = TTSModel(slug="inworld-1.5-max", name="Inworld TTS-1.5-Max", usage_multiplier=2.0)

    for vd in _load_inworld_voices():
        inworld.voices.append(Voice(**vd))  # model_id set by relationship
        inworld_max.voices.append(Voice(**vd))  # model_id set by relationship

    return [kokoro, inworld, inworld_max]


def create_plans(settings: Settings) -> list[Plan]:
    """Create subscription plans. See margin_calculator.py for pricing analysis."""
    return [
        Plan(
            tier=PlanTier.free,
            name="Free",
            server_kokoro_characters=0,
            premium_voice_characters=0,
            ocr_tokens=0,
            trial_days=0,
            price_cents_monthly=0,
            price_cents_yearly=0,
        ),
        Plan(
            tier=PlanTier.basic,
            name="Basic",
            server_kokoro_characters=None,  # unlimited
            premium_voice_characters=0,
            ocr_tokens=5_000_000,  # 5M tokens
            stripe_price_id_monthly=settings.stripe_price_basic_monthly,
            stripe_price_id_yearly=settings.stripe_price_basic_yearly,
            trial_days=3,
            price_cents_monthly=1000,
            price_cents_yearly=9000,
        ),
        Plan(
            tier=PlanTier.plus,
            name="Plus",
            server_kokoro_characters=None,  # unlimited
            premium_voice_characters=1_000_000,  # ~20 hours
            ocr_tokens=10_000_000,  # 10M tokens
            stripe_price_id_monthly=settings.stripe_price_plus_monthly,
            stripe_price_id_yearly=settings.stripe_price_plus_yearly,
            trial_days=3,
            price_cents_monthly=2000,
            price_cents_yearly=18000,
        ),
        Plan(
            tier=PlanTier.max,
            name="Max",
            server_kokoro_characters=None,  # unlimited
            premium_voice_characters=3_000_000,  # ~60 hours
            ocr_tokens=15_000_000,  # 15M tokens
            stripe_price_id_monthly=settings.stripe_price_max_monthly,
            stripe_price_id_yearly=settings.stripe_price_max_yearly,
            trial_days=0,  # No trial for Max tier
            price_cents_monthly=4000,
            price_cents_yearly=36000,
        ),
    ]


async def seed_database(db: AsyncSession, settings: Settings) -> None:
    """Seed database with models, voices, and plans.

    Idempotent — safe to leave DB_SEED=1 permanently:
    - Fresh DB: creates models, voices, and plans.
    - Existing DB: inserts any voices from voices.json missing in the DB.
    """
    existing_models = (await db.exec(select(TTSModel))).all()
    if not existing_models:
        for model in create_models():
            db.add(model)
        for plan in create_plans(settings):
            db.add(plan)
        await db.commit()

    await sync_inworld_voices(db)
    await sync_openai_tts_voices(db, settings)
    await _deactivate_unconfigured_models(db, settings)


async def sync_inworld_voices(db: AsyncSession) -> None:
    """Sync Inworld voices in DB to match voices.json (add missing, remove stale)."""
    models = (await db.exec(select(TTSModel).where(col(TTSModel.slug).startswith("inworld")))).all()
    if not models:
        return

    voice_defs = _load_inworld_voices()
    canonical_slugs = {vd["slug"] for vd in voice_defs}

    for model in models:
        existing_slugs = set((await db.exec(select(Voice.slug).where(col(Voice.model_id) == model.id))).all())

        # Add missing
        new_voices = [vd for vd in voice_defs if vd["slug"] not in existing_slugs]
        if new_voices:
            await db.exec(
                pg_insert(Voice)
                .values([{**vd, "model_id": model.id} for vd in new_voices])
                .on_conflict_do_nothing(constraint="unique_voice_per_model")
            )
            logger.info(f"Added {len(new_voices)} Inworld voices to {model.slug}: {[v['slug'] for v in new_voices]}")

        # Remove stale
        stale_slugs = existing_slugs - canonical_slugs
        if stale_slugs:
            await db.exec(delete(Voice).where(col(Voice.model_id) == model.id, col(Voice.slug).in_(stale_slugs)))
            logger.warning(f"Removed {len(stale_slugs)} stale Inworld voices from {model.slug}: {sorted(stale_slugs)}")

    await db.commit()


OPENAI_TTS_SLUG = "openai-tts"


async def _discover_voices(base_url: str) -> list[str] | None:
    """Try GET {base_url}/audio/voices — a community extension, not all servers support it."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base_url}/audio/voices")
            resp.raise_for_status()
            raw = resp.json().get("voices", [])
            if not raw:
                return None
            # Normalize: some servers return strings, others return objects
            voices = [
                v if isinstance(v, str) else v.get("name") or v.get("voice_id") or v.get("id") or str(v) for v in raw
            ]
            logger.info(f"Discovered {len(voices)} voices from {base_url}/audio/voices")
            return voices
    except Exception as e:
        logger.info(f"Voice discovery not available at {base_url}/audio/voices: {e}")
    return None


async def sync_openai_tts_voices(db: AsyncSession, settings: Settings) -> None:
    """Create or sync the openai-tts model and voices. Skips if not configured."""
    if not settings.openai_tts_base_url:
        return

    voice_names = await _discover_voices(settings.openai_tts_base_url)
    if not voice_names and settings.openai_tts_voices:
        voice_names = [v.strip() for v in settings.openai_tts_voices.split(",") if v.strip()]
    if not voice_names:
        logger.warning(
            "OpenAI TTS configured but no voices found — set OPENAI_TTS_VOICES "
            "or use a server that supports GET /v1/audio/voices"
        )
        return

    voice_defs = [
        {"slug": name, "name": name.title(), "lang": None, "parameters": {"voice": name}} for name in voice_names
    ]
    canonical_slugs = {vd["slug"] for vd in voice_defs}

    display_name = settings.openai_tts_model or "Server TTS"

    model = (await db.exec(select(TTSModel).where(TTSModel.slug == OPENAI_TTS_SLUG))).first()
    if model is None:
        model = TTSModel(slug=OPENAI_TTS_SLUG, name=display_name)
        db.add(model)
        await db.flush()
    elif model.name != display_name:
        model.name = display_name
        db.add(model)

    existing_slugs = set((await db.exec(select(Voice.slug).where(col(Voice.model_id) == model.id))).all())

    new_voices = [vd for vd in voice_defs if vd["slug"] not in existing_slugs]
    if new_voices:
        await db.exec(
            pg_insert(Voice)
            .values([{**vd, "model_id": model.id} for vd in new_voices])
            .on_conflict_do_nothing(constraint="unique_voice_per_model")
        )
        logger.info(f"Added {len(new_voices)} OpenAI TTS voices: {[v['slug'] for v in new_voices]}")

    stale_slugs = existing_slugs - canonical_slugs
    if stale_slugs:
        await db.exec(delete(Voice).where(col(Voice.model_id) == model.id, col(Voice.slug).in_(stale_slugs)))
        logger.info(f"Removed {len(stale_slugs)} stale OpenAI TTS voices: {sorted(stale_slugs)}")

    await db.commit()


async def _deactivate_unconfigured_models(db: AsyncSession, settings: Settings) -> None:
    """Set is_active on models based on whether their backend is configured."""
    inworld_active = settings.inworld_api_key is not None
    openai_tts_active = settings.openai_tts_base_url is not None

    models = (await db.exec(select(TTSModel))).all()
    changed = False
    for model in models:
        if model.slug.startswith("inworld"):
            should_be_active = inworld_active
        elif model.slug == OPENAI_TTS_SLUG:
            should_be_active = openai_tts_active
        else:
            continue
        if model.is_active != should_be_active:
            model.is_active = should_be_active
            db.add(model)
            changed = True
            logger.info(f"{'Activated' if should_be_active else 'Deactivated'} model {model.slug}")

    if changed:
        await db.commit()

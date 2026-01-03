"""Database seeding for models, voices, plans, etc."""

import base64
import json
from pathlib import Path

from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.config import Settings
from yapit.gateway.domain_models import DocumentProcessor, Filter, Plan, PlanTier, TTSModel, Voice


def load_voice_prompt(name: str) -> tuple[str, str]:
    """Load a voice prompt (audio + transcript) and return as (base64_audio, transcript)."""
    voice_dir = Path(__file__).parent.parent / "data/voice_prompts"
    audio_path = voice_dir / f"{name}.wav"
    transcript_path = voice_dir / f"{name}.txt"
    return (
        base64.b64encode(audio_path.read_bytes()).decode("utf-8"),
        transcript_path.read_text(encoding="utf-8").strip(),
    )


def create_models() -> list[TTSModel]:
    """Create TTS models with voices."""
    models = []

    kokoro = TTSModel(
        slug="kokoro",
        name="Kokoro",
        native_codec="pcm",
        sample_rate=24_000,
        channels=1,
        sample_width=2,
    )

    higgs = TTSModel(
        slug="higgs",
        name="HIGGS Audio V2",
        native_codec="pcm",
        sample_rate=24_000,
        channels=1,
        sample_width=2,
    )

    # Load kokoro voices
    voices_json = Path(__file__).parent.parent / "workers/kokoro/voices.json"
    voices_data = json.loads(voices_json.read_text())
    for v in voices_data:
        kokoro.voices.append(
            Voice(
                slug=v["index"],
                name=v["name"],
                lang=v["language"],
                description=f"Quality grade {v['overallGrade']}",
                parameters={
                    "voice": v["index"],
                    "speed": 1.0,  # we just postprocess the audio in the client for speed changes
                },
            )
        )

    # Load reference voices for HIGGS
    en_man_audio, en_man_transcript = load_voice_prompt("en_man")
    en_woman_audio, en_woman_transcript = load_voice_prompt("en_woman")

    higgs.voices.append(
        Voice(
            slug="en-man",
            name="English Male",
            lang="en",
            description="Male American accent, clear and professional.",
            parameters={
                "ref_audio": en_man_audio,
                "ref_audio_transcript": en_man_transcript,
                "seed": 42,
                "temperature": 0.3,
            },
        )
    )
    higgs.voices.append(
        Voice(
            slug="en-woman",
            name="English Female",
            lang="en",
            description="Female American accent, clear and informative.",
            parameters={
                "ref_audio": en_woman_audio,
                "ref_audio_transcript": en_woman_transcript,
                "seed": 42,
                "temperature": 0.3,
            },
        )
    )

    # Inworld TTS-1 (faster, cheaper)
    inworld = TTSModel(
        slug="inworld",
        name="Inworld TTS-1",
        native_codec="mp3",
        sample_rate=48_000,
        channels=1,
        sample_width=2,
    )

    # Inworld TTS-1-Max (slower, higher quality, 2x price)
    inworld_max = TTSModel(
        slug="inworld-max",
        name="Inworld TTS-1-Max",
        native_codec="mp3",
        sample_rate=48_000,
        channels=1,
        sample_width=2,
        usage_multiplier=2.0,
    )

    # Load Inworld voices (shared between both models)
    inworld_voices_json = Path(__file__).parent.parent / "data/inworld/voices.json"
    inworld_voices_data = json.loads(inworld_voices_json.read_text())
    for v in inworld_voices_data.get("voices", []):
        voice = Voice(
            slug=v["voiceId"].lower(),
            name=v["displayName"],
            lang=v["languages"][0] if v.get("languages") else "en",
            description=v.get("description", ""),
            parameters={"voice_id": v["voiceId"]},
        )
        inworld.voices.append(voice)
        inworld_max.voices.append(
            Voice(
                slug=v["voiceId"].lower(),
                name=v["displayName"],
                lang=v["languages"][0] if v.get("languages") else "en",
                description=v.get("description", ""),
                parameters={"voice_id": v["voiceId"]},
            )
        )

    models.extend([kokoro, higgs, inworld, inworld_max])
    return models


def create_filters() -> list[Filter]:
    """Create default filter presets."""
    presets_json = Path(__file__).parent.parent / "data/default_filters.json"
    defaults = json.loads(presets_json.read_text())

    filters = []
    for p in defaults:
        filters.append(
            Filter(
                name=p["name"],
                description=p.get("description"),
                config=p["config"],
                user_id=None,  # system filters
            )
        )
    return filters


def create_document_processors() -> list[DocumentProcessor]:
    """Create document processors."""
    return [
        DocumentProcessor(slug="markitdown", name="Markitdown (Free)"),
        DocumentProcessor(slug="mistral-ocr", name="Mistral OCR"),
    ]


def create_plans(settings: Settings) -> list[Plan]:
    """Create subscription plans.

    Pricing (EUR, tax-inclusive):
    - Free: €0, browser Kokoro only
    - Basic: €7/mo (€75/yr), unlimited server Kokoro, 500 OCR pages
    - Plus: €20/mo (€192/yr), +20 hrs premium voice, 1500 OCR pages
    - Max: €40/mo (€240/yr), +50 hrs premium voice, 3000 OCR pages

    Premium voice characters: ~17 chars = 1 second of audio
    - 20 hrs = 72,000 seconds = 1,224,000 chars
    - 50 hrs = 180,000 seconds = 3,060,000 chars

    Price IDs come from settings (env vars), different for test vs live Stripe.
    """
    return [
        Plan(
            tier=PlanTier.free,
            name="Free",
            server_kokoro_characters=0,
            premium_voice_characters=0,
            ocr_pages=0,
            trial_days=0,
            price_cents_monthly=0,
            price_cents_yearly=0,
        ),
        Plan(
            tier=PlanTier.basic,
            name="Basic",
            server_kokoro_characters=None,  # unlimited
            premium_voice_characters=0,
            ocr_pages=500,
            stripe_price_id_monthly=settings.stripe_price_basic_monthly,
            stripe_price_id_yearly=settings.stripe_price_basic_yearly,
            trial_days=3,
            price_cents_monthly=700,
            price_cents_yearly=7500,
        ),
        Plan(
            tier=PlanTier.plus,
            name="Plus",
            server_kokoro_characters=None,  # unlimited
            premium_voice_characters=1_224_000,  # 20 hours
            ocr_pages=1500,
            stripe_price_id_monthly=settings.stripe_price_plus_monthly,
            stripe_price_id_yearly=settings.stripe_price_plus_yearly,
            trial_days=3,
            price_cents_monthly=2000,
            price_cents_yearly=19200,
        ),
        Plan(
            tier=PlanTier.max,
            name="Max",
            server_kokoro_characters=None,  # unlimited
            premium_voice_characters=3_060_000,  # 50 hours
            ocr_pages=3000,
            stripe_price_id_monthly=settings.stripe_price_max_monthly,
            stripe_price_id_yearly=settings.stripe_price_max_yearly,
            trial_days=0,  # No trial for Max tier
            price_cents_monthly=4000,
            price_cents_yearly=24000,
        ),
    ]


async def seed_database(db: AsyncSession, settings: Settings) -> None:
    """Seed database with models, voices, filters, processors, and plans."""
    for model in create_models():
        db.add(model)

    for filter_obj in create_filters():
        db.add(filter_obj)

    for processor in create_document_processors():
        db.add(processor)

    for plan in create_plans(settings):
        db.add(plan)

    await db.commit()

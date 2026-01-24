"""Database seeding for models, voices, plans, etc."""

import base64
import json
from pathlib import Path

from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.config import Settings
from yapit.gateway.domain_models import DocumentProcessor, Plan, PlanTier, TTSModel, Voice


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

    # Inworld TTS-1.5-Mini (faster, cheaper)
    inworld = TTSModel(
        slug="inworld-1.5",
        name="Inworld TTS-1.5",
        native_codec="mp3",
        sample_rate=48_000,
        channels=1,
        sample_width=2,
    )

    # Inworld TTS-1.5-Max (slower, higher quality, 2x price)
    inworld_max = TTSModel(
        slug="inworld-1.5-max",
        name="Inworld TTS-1.5-Max",
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


def create_document_processors() -> list[DocumentProcessor]:
    """Create document processors."""
    return [
        DocumentProcessor(slug="markitdown", name="Markitdown (Free)"),
        DocumentProcessor(slug="mistral-ocr", name="Mistral OCR"),
    ]


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
    """Seed database with models, voices, processors, and plans."""
    for model in create_models():
        db.add(model)

    for processor in create_document_processors():
        db.add(processor)

    for plan in create_plans(settings):
        db.add(plan)

    await db.commit()

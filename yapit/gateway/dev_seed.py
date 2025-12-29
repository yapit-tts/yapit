"""Development database seeding."""

import base64
import json
from decimal import Decimal
from pathlib import Path

from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.domain_models import CreditPackage, DocumentProcessor, Filter, TTSModel, Voice


def load_voice_prompt(name: str) -> tuple[str, str]:
    """Load a voice prompt (audio + transcript) and return as (base64_audio, transcript)."""
    voice_dir = Path(__file__).parent.parent / "data/voice_prompts"
    audio_path = voice_dir / f"{name}.wav"
    transcript_path = voice_dir / f"{name}.txt"
    return (
        base64.b64encode(audio_path.read_bytes()).decode("utf-8"),
        transcript_path.read_text(encoding="utf-8").strip(),
    )


def create_dev_models() -> list[TTSModel]:
    """Create development TTS models with voices."""
    models = []

    kokoro = TTSModel(
        slug="kokoro",
        name="Kokoro",
        credits_per_sec=Decimal("1.0"),  # charged when synthesis_mode=server
        native_codec="pcm",
        sample_rate=24_000,
        channels=1,
        sample_width=2,
    )

    higgs = TTSModel(
        slug="higgs",
        name="HIGGS Audio V2",
        credits_per_sec=Decimal("2.0"),
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

    models.extend([kokoro, higgs])

    # Uncomment to add Dia model
    # dia = TTSModel(
    #     slug="dia",
    #     name="Dia-1.6B",
    #     credits_per_sec=Decimal("2.0"),
    #     native_codec="pcm",
    #     sample_rate=44_100,
    #     channels=1,
    #     sample_width=2,
    # )
    # dia.voices.append(Voice(slug="default", name="Dia", lang="en"))
    # models.append(dia)

    return models


def create_dev_filters() -> list[Filter]:
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


def create_dev_document_processors() -> list[DocumentProcessor]:
    """Create document processors for development."""
    processors = [
        DocumentProcessor(
            slug="markitdown",
            name="Markitdown (Free)",
            credits_per_page=Decimal("0"),  # Free processor
        ),
        DocumentProcessor(
            slug="mistral-ocr",
            name="Mistral OCR",
            credits_per_page=Decimal("10"),  # 10 credits per page
        ),
    ]
    return processors


def create_dev_credit_packages() -> list[CreditPackage]:
    """Create default credit packages for purchase."""
    packages = [
        CreditPackage(
            provider_price_id="price_dev_starter",
            credits=Decimal("10000"),
        ),
        CreditPackage(
            provider_price_id="price_dev_basic",
            credits=Decimal("50000"),
        ),
        CreditPackage(
            provider_price_id="price_dev_pro",
            credits=Decimal("100000"),
        ),
    ]
    return packages


async def seed_dev_database(db: AsyncSession) -> None:
    """Seed development database with models, filters, document processors, and credit packages."""
    # Add all TTS models
    for model in create_dev_models():
        db.add(model)

    # Add default filters
    for filter_obj in create_dev_filters():
        db.add(filter_obj)

    # Add document processors
    for processor in create_dev_document_processors():
        db.add(processor)

    # Add credit packages
    for package in create_dev_credit_packages():
        db.add(package)

    await db.commit()

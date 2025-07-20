"""Development database seeding."""

import json
from decimal import Decimal
from pathlib import Path

from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.domain_models import CreditPackage, DocumentProcessor, Filter, TTSModel, Voice


def create_dev_models() -> list[TTSModel]:
    """Create development TTS models with voices."""
    models = []

    # Local CPU worker
    kokoro_cpu = TTSModel(
        slug="kokoro-cpu",
        name="Kokoro (CPU)",
        credit_multiplier=Decimal("1.0"),
        native_codec="pcm",
        sample_rate=24_000,
        channels=1,
        sample_width=2,
    )

    # RunPod CPU worker (for testing)
    kokoro_cpu_runpod = TTSModel(
        slug="kokoro-cpu-runpod",
        name="Kokoro (CPU on RunPod)",
        credit_multiplier=Decimal("1.5"),
        native_codec="pcm",
        sample_rate=24_000,
        channels=1,
        sample_width=2,
    )

    # Load voices for both models
    voices_json = Path(__file__).parent.parent / "workers/kokoro/voices.json"
    voices_data = json.loads(voices_json.read_text())

    for v in voices_data:
        voice_kwargs = {
            "slug": v["index"],
            "name": v["name"],
            "lang": v["language"],
            "description": f"Quality grade {v['overallGrade']}",
        }
        kokoro_cpu.voices.append(Voice(**voice_kwargs))
        kokoro_cpu_runpod.voices.append(Voice(**voice_kwargs))

    models.extend([kokoro_cpu, kokoro_cpu_runpod])

    # Uncomment to add Dia model
    # dia = TTSModel(
    #     slug="dia",
    #     name="Dia-1.6B",
    #     credit_multiplier=Decimal("2.0"),
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

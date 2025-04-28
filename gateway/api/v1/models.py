from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from gateway.db import get_db
from gateway.domain_models import Model

router = APIRouter(prefix="/v1/models", tags=["Models"])


class VoiceRead(BaseModel):
    id: int
    slug: str
    name: str
    lang: str


class ModelRead(BaseModel):
    id: int
    slug: str
    name: str
    description: str | None = None
    price_sec: float
    voices: list[VoiceRead] = []


@router.get("", response_model=List[ModelRead])
async def list_models(
    db: AsyncSession = Depends(get_db),
) -> List[ModelRead]:
    """Get all available TTS models with their voices."""
    # Using SQLModel's exec() instead of execute()
    # This returns proper Model objects directly
    results = await db.exec(select(Model))
    models = results.all()

    # Convert to response model with explicit typing
    return [
        ModelRead(
            id=model.id,
            slug=model.slug,
            name=model.name,
            description=model.description,
            price_sec=model.price_sec,
            voices=[
                VoiceRead(
                    id=voice.id,
                    slug=voice.slug,
                    name=voice.name,
                    lang=voice.lang,
                )
                for voice in model.voices
            ],
        )
        for model in models
    ]


@router.get("/{model_slug}", response_model=ModelRead)
async def get_model(
    model_slug: str,
    db: AsyncSession = Depends(get_db),
) -> ModelRead:
    """Get a specific TTS model by slug."""
    result = await db.exec(select(Model).where(Model.slug == model_slug))
    model = result.first()

    if not model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")

    return ModelRead(
        id=model.id,
        slug=model.slug,
        name=model.name,
        description=model.description,
        price_sec=model.price_sec,
        voices=[
            VoiceRead(
                id=voice.id,
                slug=voice.slug,
                name=voice.name,
                lang=voice.lang,
            )
            for voice in model.voices
        ],
    )


@router.get("/{model_slug}/voices", response_model=List[VoiceRead])
async def list_voices(
    model_slug: str,
    db: AsyncSession = Depends(get_db),
) -> List[VoiceRead]:
    """Get all voices available for a specific model."""
    result = await db.exec(select(Model).where(Model.slug == model_slug))
    model = result.first()

    if not model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")

    return [
        VoiceRead(
            id=voice.id,
            slug=voice.slug,
            name=voice.name,
            lang=voice.lang,
        )
        for voice in model.voices
    ]

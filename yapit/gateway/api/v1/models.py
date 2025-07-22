from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import select

from yapit.gateway.auth import authenticate
from yapit.gateway.db import get_by_slug_or_404
from yapit.gateway.deps import CurrentTTSModel, DbSession
from yapit.gateway.domain_models import TTSModel

router = APIRouter(prefix="/v1/models", tags=["Models"])


class VoiceRead(BaseModel):
    id: int
    slug: str
    name: str
    lang: str
    description: str | None


class ModelRead(BaseModel):
    id: int
    slug: str
    name: str
    description: str | None = None
    credits_per_sec: float
    voices: list[VoiceRead] = []


@router.get("", response_model=List[ModelRead], dependencies=[Depends(authenticate)])
async def list_models(
    db: DbSession,
) -> List[ModelRead]:
    """Get all available TTS models with their voices."""
    models = (await db.exec(select(TTSModel))).all()
    return [
        ModelRead(
            id=model.id,
            slug=model.slug,
            name=model.name,
            description=model.description,
            credits_per_sec=model.credits_per_sec,
            voices=[
                VoiceRead(
                    id=voice.id,
                    slug=voice.slug,
                    name=voice.name,
                    lang=voice.lang,
                    description=voice.description,
                )
                for voice in model.voices
            ],
        )
        for model in models
    ]


@router.get("/{model_slug}", response_model=ModelRead, dependencies=[Depends(authenticate)])
async def read_model(
    model: CurrentTTSModel,
) -> ModelRead:
    """Get a specific TTS model by slug."""
    return ModelRead(
        id=model.id,
        slug=model.slug,
        name=model.name,
        description=model.description,
        credits_per_sec=model.credits_per_sec,
        voices=[
            VoiceRead(
                id=voice.id,
                slug=voice.slug,
                name=voice.name,
                lang=voice.lang,
                description=voice.description,
            )
            for voice in model.voices
        ],
    )


@router.get("/{model_slug}/voices", response_model=List[VoiceRead])
async def list_voices(
    model_slug: str,
    db: DbSession,
) -> List[VoiceRead]:
    """Get all voices available for a specific model."""
    model = await get_by_slug_or_404(db, TTSModel, model_slug)

    return [
        VoiceRead(
            id=voice.id,
            slug=voice.slug,
            name=voice.name,
            lang=voice.lang,
            description=voice.description,
        )
        for voice in model.voices
    ]

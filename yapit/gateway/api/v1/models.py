from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import col, select

from yapit.gateway.auth import authenticate
from yapit.gateway.db import get_by_slug_or_404
from yapit.gateway.deps import CurrentTTSModel, DbSession
from yapit.gateway.domain_models import TTSModel

router = APIRouter(prefix="/v1/models", tags=["Models"])


class VoiceRead(BaseModel):
    id: int
    slug: str
    name: str
    lang: str | None
    description: str | None


class ModelRead(BaseModel):
    id: int
    slug: str
    name: str
    description: str | None = None
    voices: list[VoiceRead] = []


@router.get("", response_model=List[ModelRead], dependencies=[Depends(authenticate)])
async def list_models(
    db: DbSession,
) -> List[ModelRead]:
    """Get all available TTS models with their voices (only active ones)."""
    models = (await db.exec(select(TTSModel).where(col(TTSModel.is_active).is_(True)))).all()
    return [
        ModelRead(
            id=model.id,
            slug=model.slug,
            name=model.name,
            description=model.description,
            voices=[
                VoiceRead(
                    id=voice.id,
                    slug=voice.slug,
                    name=voice.name,
                    lang=voice.lang,
                    description=voice.description,
                )
                for voice in model.voices
                if voice.is_active
            ],
        )
        for model in models
    ]


@router.get("/{model_slug}", response_model=ModelRead, dependencies=[Depends(authenticate)])
async def read_model(
    model: CurrentTTSModel,
) -> ModelRead:
    """Get a specific TTS model by slug (active voices only)."""
    return ModelRead(
        id=model.id,
        slug=model.slug,
        name=model.name,
        description=model.description,
        voices=[
            VoiceRead(
                id=voice.id,
                slug=voice.slug,
                name=voice.name,
                lang=voice.lang,
                description=voice.description,
            )
            for voice in model.voices
            if voice.is_active
        ],
    )


@router.get("/{model_slug}/voices", response_model=List[VoiceRead])
async def list_voices(
    model_slug: str,
    db: DbSession,
) -> List[VoiceRead]:
    """Get all active voices available for a specific model."""
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
        if voice.is_active
    ]

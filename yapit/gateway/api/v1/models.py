from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import select

from yapit.gateway.auth import authenticate
from yapit.gateway.deps import AuthenticatedUser, CurrentTTSModel, DbSession
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
    price_sec: float
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
            price_sec=model.price_sec,
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
        price_sec=model.price_sec,
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
    model = (await db.exec(select(TTSModel).where(TTSModel.slug == model_slug))).first()

    if not model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")

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

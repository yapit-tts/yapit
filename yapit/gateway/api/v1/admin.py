from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import select

from yapit.gateway.db import get_by_slug_or_404
from yapit.gateway.deps import DbSession, require_admin
from yapit.gateway.domain_models import (
    TTSModel,
    Voice,
)
from yapit.gateway.exceptions import ResourceNotFoundError

router = APIRouter(prefix="/v1/admin", tags=["Admin"], dependencies=[Depends(require_admin)])


class ModelCreateRequest(BaseModel):
    """Request to create a new TTS model."""

    slug: str
    name: str
    native_codec: str
    sample_rate: int
    channels: int
    sample_width: int


class ModelUpdateRequest(BaseModel):
    """Request to update a TTS model."""

    name: str | None = None
    native_codec: str | None = None
    sample_rate: int | None = None
    channels: int | None = None
    sample_width: int | None = None


class VoiceCreateRequest(BaseModel):
    """Request to create a new voice."""

    slug: str
    name: str
    lang: str
    description: str | None = None


class VoiceUpdateRequest(BaseModel):
    """Request to update a voice."""

    name: str | None = None
    lang: str | None = None
    description: str | None = None


# Models CRUD


@router.post("/models", status_code=status.HTTP_201_CREATED)
async def create_model(
    model_data: ModelCreateRequest,
    db: DbSession,
) -> TTSModel:
    """Create a new TTS model."""
    existing = (await db.exec(select(TTSModel).where(TTSModel.slug == model_data.slug))).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{TTSModel.__name__} with identifier {model_data.slug!r} already exists",
        )

    model = TTSModel(**model_data.model_dump())
    db.add(model)
    await db.commit()
    await db.refresh(model)
    return model


@router.put("/models/{model_slug}")
async def update_model(
    model_slug: str,
    model_data: ModelUpdateRequest,
    db: DbSession,
) -> TTSModel:
    """Update an existing TTS model."""
    model = await get_by_slug_or_404(db, TTSModel, model_slug)

    update_data = model_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(model, key, value)

    await db.commit()
    await db.refresh(model)
    return model


@router.delete("/models/{model_slug}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(
    model_slug: str,
    db: DbSession,
) -> None:
    """Delete a TTS model and all its voices."""
    model = await get_by_slug_or_404(db, TTSModel, model_slug)

    await db.delete(model)
    await db.commit()


# Voices CRUD


@router.post("/models/{model_slug}/voices", status_code=status.HTTP_201_CREATED)
async def create_voice(
    model_slug: str,
    voice_data: VoiceCreateRequest,
    db: DbSession,
) -> Voice:
    """Create a new voice for a model."""
    model = await get_by_slug_or_404(db, TTSModel, model_slug)

    existing = (
        await db.exec(select(Voice).where(Voice.slug == voice_data.slug).where(Voice.model_id == model.id))
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{Voice.__name__} with slug {voice_data.slug!r} already exists for model {model_slug!r}",
        )

    voice = Voice(**voice_data.model_dump(), model_id=model.id)
    db.add(voice)
    await db.commit()
    await db.refresh(voice)
    return voice


@router.put("/models/{model_slug}/voices/{voice_slug}")
async def update_voice(
    model_slug: str,
    voice_slug: str,
    voice_data: VoiceUpdateRequest,
    db: DbSession,
) -> Voice:
    """Update an existing voice."""
    voice = (
        await db.exec(select(Voice).join(TTSModel).where(Voice.slug == voice_slug).where(TTSModel.slug == model_slug))
    ).first()
    if not voice:
        raise ResourceNotFoundError(
            Voice.__name__, voice_slug, message=f"Voice {voice_slug!r} not found for model {model_slug!r}"
        )

    update_data = voice_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(voice, key, value)

    await db.commit()
    await db.refresh(voice)
    return voice


@router.delete("/models/{model_slug}/voices/{voice_slug}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_voice(
    model_slug: str,
    voice_slug: str,
    db: DbSession,
) -> None:
    """Delete a voice."""
    voice = (
        await db.exec(select(Voice).join(TTSModel).where(Voice.slug == voice_slug).where(TTSModel.slug == model_slug))
    ).first()
    if not voice:
        raise ResourceNotFoundError(
            Voice.__name__, voice_slug, message=f"Voice {voice_slug!r} not found for model {model_slug!r}"
        )

    await db.delete(voice)
    await db.commit()

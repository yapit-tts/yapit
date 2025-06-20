from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import select

from yapit.gateway.deps import DbSession, require_admin
from yapit.gateway.domain_models import Filter, TTSModel, Voice

router = APIRouter(prefix="/v1/admin", tags=["Admin"], dependencies=[Depends(require_admin)])


class ModelCreateRequest(BaseModel):
    """Request to create a new TTS model."""

    slug: str
    name: str
    price_sec: float
    native_codec: str
    sample_rate: int
    channels: int
    sample_width: int


class ModelUpdateRequest(BaseModel):
    """Request to update a TTS model."""

    name: str | None = None
    price_sec: float | None = None
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


class FilterCreateRequest(BaseModel):
    """Request to create a system filter."""

    name: str
    description: str | None = None
    config: dict


class FilterUpdateRequest(BaseModel):
    """Request to update a system filter."""

    name: str | None = None
    description: str | None = None
    config: dict | None = None


# Models CRUD


@router.post("/models", status_code=status.HTTP_201_CREATED)
async def create_model(
    model_data: ModelCreateRequest,
    db: DbSession,
) -> TTSModel:
    """Create a new TTS model."""
    # Check if model with slug already exists
    existing = (await db.exec(select(TTSModel).where(TTSModel.slug == model_data.slug))).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Model with slug {model_data.slug!r} already exists",
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
    model = (await db.exec(select(TTSModel).where(TTSModel.slug == model_slug))).first()
    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model {model_slug!r} not found",
        )

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
    model = (await db.exec(select(TTSModel).where(TTSModel.slug == model_slug))).first()
    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model {model_slug!r} not found",
        )

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
    model = (await db.exec(select(TTSModel).where(TTSModel.slug == model_slug))).first()
    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model {model_slug!r} not found",
        )

    # Check if voice with slug already exists for this model
    existing = (
        await db.exec(select(Voice).where(Voice.slug == voice_data.slug).where(Voice.model_id == model.id))
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Voice with slug {voice_data.slug!r} already exists for model {model_slug!r}",
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Voice {voice_slug!r} not found for model {model_slug!r}",
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Voice {voice_slug!r} not found for model {model_slug!r}",
        )

    await db.delete(voice)
    await db.commit()


# System Filters CRUD


@router.get("/filters")
async def list_system_filters(
    db: DbSession,
) -> list[Filter]:
    """List all system filters (filters with no user_id)."""
    filters = await db.exec(select(Filter).where(Filter.user_id == None))
    return list(filters)


@router.post("/filters", status_code=status.HTTP_201_CREATED)
async def create_system_filter(
    filter_data: FilterCreateRequest,
    db: DbSession,
) -> Filter:
    """Create a new system filter."""
    # Check if system filter with name already exists
    existing = (
        await db.exec(select(Filter).where(Filter.name == filter_data.name).where(Filter.user_id == None))
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"System filter with name {filter_data.name!r} already exists",
        )

    filter_obj = Filter(**filter_data.model_dump(), user_id=None)
    db.add(filter_obj)
    await db.commit()
    await db.refresh(filter_obj)
    return filter_obj


@router.put("/filters/{filter_id}")
async def update_system_filter(
    filter_id: int,
    filter_data: FilterUpdateRequest,
    db: DbSession,
) -> Filter:
    """Update an existing system filter."""
    filter_obj = await db.get(Filter, filter_id)
    if not filter_obj or filter_obj.user_id is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"System filter {filter_id!r} not found",
        )

    # Check name uniqueness if updating name (relevant only for system filters)
    if filter_data.name and filter_data.name != filter_obj.name:
        existing = (
            await db.exec(
                select(Filter)
                .where(Filter.name == filter_data.name)
                .where(Filter.user_id == None)
                .where(Filter.id != filter_id)
            )
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"System filter with name {filter_data.name!r} already exists",
            )

    update_data = filter_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(filter_obj, key, value)

    await db.commit()
    await db.refresh(filter_obj)
    return filter_obj


@router.delete("/filters/{filter_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_system_filter(
    filter_id: int,
    db: DbSession,
) -> None:
    """Delete a system filter."""
    filter_obj = await db.get(Filter, filter_id)
    if not filter_obj or filter_obj.user_id is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"System filter {filter_id!r} not found",
        )

    await db.delete(filter_obj)
    await db.commit()

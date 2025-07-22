from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import select

from yapit.gateway.db import get_by_slug_or_404, get_or_404
from yapit.gateway.deps import (
    DbSession,
    get_or_create_user_credits,
    require_admin,
)
from yapit.gateway.domain_models import (
    CreditTransaction,
    Filter,
    TransactionStatus,
    TransactionType,
    TTSModel,
    UserCredits,
    Voice,
)
from yapit.gateway.exceptions import ResourceNotFoundError

router = APIRouter(prefix="/v1/admin", tags=["Admin"], dependencies=[Depends(require_admin)])


class ModelCreateRequest(BaseModel):
    """Request to create a new TTS model."""

    slug: str
    name: str
    credits_per_sec: Decimal
    native_codec: str
    sample_rate: int
    channels: int
    sample_width: int


class ModelUpdateRequest(BaseModel):
    """Request to update a TTS model."""

    name: str | None = None
    credits_per_sec: Decimal | None = None
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


# System Filters CRUD


@router.get("/filters")
async def list_system_filters(
    db: DbSession,
) -> list[Filter]:
    """List all system filters (filters with no user_id)."""
    result = await db.exec(select(Filter).where(Filter.user_id == None))
    return result.all()


@router.post("/filters", status_code=status.HTTP_201_CREATED)
async def create_system_filter(
    filter_data: FilterCreateRequest,
    db: DbSession,
) -> Filter:
    """Create a new system filter."""
    existing = (
        await db.exec(select(Filter).where(Filter.name == filter_data.name).where(Filter.user_id == None))
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{Filter.__name__} with identifier {filter_data.name!r} already exists",
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
    filter_obj = await get_or_404(db, Filter, filter_id)
    if filter_obj.user_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"The filter {filter_id!r} is not a system filter"
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
                detail=f"{Filter.__name__} with identifier {filter_data.name!r} already exists",
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
    filter_obj = await get_or_404(db, Filter, filter_id)
    if filter_obj.user_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"The filter {filter_id!r} is not a system filter"
        )

    await db.delete(filter_obj)
    await db.commit()


# Credit Management Endpoints


class CreditAdjustmentRequest(BaseModel):
    """Request to adjust user credits."""

    amount: Decimal
    description: str
    type: TransactionType = TransactionType.credit_adjustment


@router.post("/users/{user_id}/credits", response_model=UserCredits)
async def adjust_user_credits(
    user_id: str,
    adjustment: CreditAdjustmentRequest,
    db: DbSession,
) -> UserCredits:
    """Adjust user's credit balance (grant, deduct, or refund credits)."""
    user_credits = await get_or_create_user_credits(user_id, db)
    await db.flush()

    balance_before = user_credits.balance
    user_credits.balance += adjustment.amount

    # Update totals based on transaction type
    if adjustment.type in [TransactionType.credit_purchase, TransactionType.credit_bonus]:
        user_credits.total_purchased += adjustment.amount
    elif adjustment.type == TransactionType.usage_deduction and adjustment.amount < 0:
        user_credits.total_used += abs(adjustment.amount)

    transaction = CreditTransaction(
        user_id=user_id,
        type=adjustment.type,
        status=TransactionStatus.completed,
        amount=adjustment.amount,
        balance_before=balance_before,
        balance_after=user_credits.balance,
        description=adjustment.description,
        details={"adjusted_by": "admin"},
    )
    db.add(transaction)

    await db.commit()
    await db.refresh(user_credits)
    return user_credits

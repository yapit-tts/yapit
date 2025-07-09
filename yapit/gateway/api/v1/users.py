from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlmodel import select

from yapit.gateway.deps import (
    AuthenticatedUser,
    DbSession,
)
from yapit.gateway.domain_models import (
    CreditTransaction,
    Filter,
    FilterConfig,
    UserCredits,
)

router = APIRouter(prefix="/v1/users", tags=["Users"])


class UserCreditsResponse(BaseModel):
    """Response containing user's credit information."""

    user_id: str
    balance: Decimal
    total_purchased: Decimal
    total_used: Decimal


class FilterRead(BaseModel):
    """User filter response."""

    id: int
    name: str
    description: str | None
    config: dict[str, Any]


@router.get("/me/credits", response_model=UserCreditsResponse)
async def get_my_credits(
    db: DbSession,
    auth_user: AuthenticatedUser,
) -> UserCredits:
    """Get current user's credit balance and statistics."""
    user_credits = await db.get(UserCredits, auth_user.id)
    if not user_credits:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No credit record found",
        )
    return user_credits


@router.get("/me/transactions")
async def get_my_transactions(
    db: DbSession,
    auth_user: AuthenticatedUser,
    limit: int = 50,
    offset: int = 0,
) -> list[CreditTransaction]:
    """Get current user's credit transaction history."""
    result = await db.exec(
        select(CreditTransaction)
        .where(CreditTransaction.user_id == auth_user.id)
        .order_by(CreditTransaction.created.desc())
        .limit(limit)
        .offset(offset)
    )
    return result.all()


@router.get("/{user_id}/filters", response_model=list[FilterRead])
async def list_user_filters(
    user_id: str,
    db: DbSession,
    auth_user: AuthenticatedUser,
) -> list[FilterRead]:
    """List filters for a specific user (own filters only)."""
    if user_id != auth_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot view other users' filters")
    result = await db.exec(select(Filter).where(Filter.user_id == user_id))
    filters = result.all()
    return [
        FilterRead(
            id=f.id,
            name=f.name,
            description=f.description,
            config=f.config.model_dump() if isinstance(f.config, FilterConfig) else f.config,
        )
        for f in filters
    ]

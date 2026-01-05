from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlmodel import select

from yapit.gateway.deps import AuthenticatedUser, DbSession
from yapit.gateway.domain_models import Filter, FilterConfig
from yapit.gateway.usage import get_usage_summary

router = APIRouter(prefix="/v1/users", tags=["Users"])


class FilterRead(BaseModel):
    """User filter response."""

    id: int
    name: str
    description: str | None
    config: dict[str, Any]


@router.get("/me/subscription")
async def get_my_subscription(
    db: DbSession,
    auth_user: AuthenticatedUser,
) -> dict:
    """Get current user's subscription and usage summary."""
    return await get_usage_summary(auth_user.id, db)


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

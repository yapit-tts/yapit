from __future__ import annotations

from typing import Any

import re2 as re
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import select

from yapit.gateway.auth import authenticate
from yapit.gateway.deps import DbSession
from yapit.gateway.domain_models import Filter, FilterConfig

router = APIRouter(prefix="/v1", tags=["Filters"])


class FilterJobRequest(BaseModel):
    filter_config: FilterConfig


class SimpleMessage(BaseModel):
    message: str


class FilterRead(BaseModel):
    id: int
    name: str
    description: str | None
    config: dict[str, Any]


@router.post("/filters/validate", response_model=SimpleMessage, dependencies=[Depends(authenticate)])
def validate_regex(
    body: FilterJobRequest,
) -> SimpleMessage:
    for rule in (body.filter_config or FilterConfig()).regex_rules:
        try:
            re.compile(rule.pattern)
        except re.error as exc:
            raise HTTPException(422, f"Invalid regex: {exc}") from exc
    return SimpleMessage(message="ok")


@router.get("/filters/system", response_model=list[FilterRead])
async def list_system_filters(
    db: DbSession,
) -> list[FilterRead]:
    """List system-provided filters available to all users."""
    filters_query = select(Filter).where(Filter.user_id == None)
    filters = (await db.exec(filters_query)).all()
    return [
        FilterRead(
            id=f.id,
            name=f.name,
            description=f.description,
            config=f.config.model_dump() if isinstance(f.config, FilterConfig) else f.config,
        )
        for f in filters
    ]

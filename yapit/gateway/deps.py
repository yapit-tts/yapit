from __future__ import annotations

from typing import Annotated, AsyncIterator
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from redis.asyncio import Redis
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.auth import authenticate
from yapit.gateway.cache import Cache, CacheConfig, Caches, SqliteCache
from yapit.gateway.config import Settings, get_settings
from yapit.gateway.db import create_session, get_by_slug_or_404, get_or_404
from yapit.gateway.document.base import BaseDocumentProcessor
from yapit.gateway.domain_models import (
    Block,
    BlockVariant,
    Document,
    TTSModel,
    Voice,
)
from yapit.gateway.exceptions import ResourceNotFoundError
from yapit.gateway.stack_auth.users import User

SettingsDep = Annotated[Settings, Depends(get_settings)]


def create_cache(cache_type: Caches, config: CacheConfig) -> Cache:
    """Create a new cache instance. Used during app startup."""
    match cache_type:
        case Caches.SQLITE:
            return SqliteCache(config)


async def get_audio_cache(request: Request) -> Cache:
    return request.app.state.audio_cache


async def get_document_cache(request: Request) -> Cache:
    return request.app.state.document_cache


async def get_extraction_cache(request: Request) -> Cache:
    return request.app.state.extraction_cache


async def get_db_session(settings: Settings = Depends(get_settings)) -> AsyncIterator[AsyncSession]:
    async for session in create_session(settings):
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db_session)]


async def get_doc(
    document_id: UUID,
    db: DbSession,
    user: AuthenticatedUser,
) -> Document:
    doc = await get_or_404(db, Document, document_id)
    if doc.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot access document of another user")
    return doc


async def get_model(
    db: DbSession,
    model_slug: str,
) -> TTSModel:
    return await get_by_slug_or_404(db, TTSModel, model_slug)


CurrentTTSModel = Annotated[TTSModel, Depends(get_model)]


async def get_voice(
    db: DbSession,
    model_slug: str,
    voice_slug: str,
) -> Voice:
    voice: Voice | None = (
        await db.exec(select(Voice).join(TTSModel).where(Voice.slug == voice_slug, TTSModel.slug == model_slug))
    ).first()
    if not voice:
        raise ResourceNotFoundError(
            Voice.__name__, voice_slug, message=f"Voice {voice_slug!r} not configured for model {model_slug!r}"
        )
    return voice


async def get_block(
    document_id: UUID,
    block_id: int,
    db: DbSession,
    user: AuthenticatedUser,
) -> Block:
    block = await get_or_404(db, Block, block_id, options=[selectinload("*")])
    if block.document_id != document_id:
        raise ResourceNotFoundError(
            Block.__name__, block_id, message=f"Block {block_id!r} not found in document {document_id!r}"
        )

    if block.document.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Cannot access block in another user's document"
        )

    return block


async def get_block_variant(
    variant_hash: str,
    db: DbSession,
    user: AuthenticatedUser,
) -> BlockVariant:
    variant = await get_or_404(
        db,
        BlockVariant,
        variant_hash,
        options=[
            selectinload(BlockVariant.block).selectinload(Block.document),  # type: ignore[arg-type]
            selectinload(BlockVariant.model),  # type: ignore[arg-type]
        ],
    )

    if variant.block.document.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Cannot access block variant in another user's document"
        )
    return variant


async def is_admin(user: Annotated[User, Depends(authenticate)]) -> bool:
    """Check if the authenticated user is an admin."""
    return bool(user.server_metadata and user.server_metadata.is_admin)


async def require_admin(is_admin: IsAdmin) -> None:
    """Require the authenticated user to be an admin."""
    if not is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")


async def get_redis_client(request: Request) -> Redis:
    return request.app.state.redis_client


async def get_free_processor(request: Request) -> BaseDocumentProcessor:
    return request.app.state.free_processor


async def get_ai_processor(request: Request) -> BaseDocumentProcessor | None:
    return request.app.state.ai_processor


RedisClient = Annotated[Redis, Depends(get_redis_client)]
FreeProcessorDep = Annotated[BaseDocumentProcessor, Depends(get_free_processor)]
AiProcessorDep = Annotated[BaseDocumentProcessor | None, Depends(get_ai_processor)]
AudioCache = Annotated[Cache, Depends(get_audio_cache)]
DocumentCache = Annotated[Cache, Depends(get_document_cache)]
ExtractionCache = Annotated[Cache, Depends(get_extraction_cache)]
CurrentDoc = Annotated[Document, Depends(get_doc)]
CurrentVoice = Annotated[Voice, Depends(get_voice)]
CurrentBlock = Annotated[Block, Depends(get_block)]
CurrentBlockVariant = Annotated[BlockVariant, Depends(get_block_variant)]
AuthenticatedUser = Annotated[User, Depends(authenticate)]
IsAdmin = Annotated[bool, Depends(is_admin)]

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, AsyncIterator, Callable
from uuid import UUID

from fastapi import Body, Depends, HTTPException, Request, status
from redis.asyncio import Redis
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.auth import authenticate
from yapit.gateway.cache import Cache, Caches, SqliteCache
from yapit.gateway.config import Settings, get_settings
from yapit.gateway.db import create_session
from yapit.gateway.domain_models import Block, BlockVariant, Document, TTSModel, UserCredits, Voice
from yapit.gateway.processors.document.manager import DocumentProcessorManager
from yapit.gateway.stack_auth.users import User
from yapit.gateway.text_splitter import (
    DummySplitter,
    HierarchicalSplitter,
    TextSplitter,
    TextSplitters,
)

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_audio_cache(settings: SettingsDep) -> Cache:
    audio_cache_type = settings.audio_cache_type.lower()
    if audio_cache_type == Caches.SQLITE.name.lower():
        return SqliteCache(settings.audio_cache_config)
    else:
        raise ValueError(rf"Invalid audio cache type {settings.audio_cache_type}")


def get_document_cache(settings: SettingsDep) -> Cache:
    document_cache_type = settings.document_cache_type.lower()
    if document_cache_type == Caches.SQLITE.name.lower():
        return SqliteCache(settings.document_cache_config)
    else:
        raise ValueError(rf"Invalid document cache type {settings.document_cache_type}")


def get_text_splitter(settings: SettingsDep) -> TextSplitter:
    splitter_type = settings.splitter_type.lower()
    if splitter_type == TextSplitters.DUMMY.name.lower():
        return DummySplitter(settings.splitter_config)
    elif splitter_type == TextSplitters.HIERARCHICAL.name.lower():
        return HierarchicalSplitter(settings.splitter_config)
    else:
        raise ValueError(rf"Invalid TextSplitter type {settings.splitter_type}")


async def get_db_session(
    settings: Settings = Depends(get_settings),
) -> AsyncIterator[AsyncSession]:
    async for session in create_session(settings):
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db_session)]


async def get_doc(
    document_id: UUID,
    db: DbSession,
    user: AuthenticatedUser,
) -> Document:
    doc: Document | None = await db.get(Document, document_id)
    if not doc:
        raise HTTPException(404, f"Document {document_id!r} not found")

    if doc.user_id != user.id:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "cannot access document of another user",
        )

    return doc


def _get_param_extractor(name: str) -> Callable:
    """Helper to return a FastAPI dependency that fetches `name` from path/query or JSON."""

    async def extract(
        value: str | None = None,  # from url path or query parameter
        body: dict | None = Body(None),  # from already-parsed JSON
    ) -> str:
        if value:
            return value
        if body and name in body:
            return body[name]
        raise HTTPException(422, f"{name} missing")

    extract.__name__ = f"extract_{name}"
    return extract


ModelSlug = Annotated[str, Depends(_get_param_extractor("model_slug"))]
VoiceSlug = Annotated[str, Depends(_get_param_extractor("voice_slug"))]


async def get_model(
    db: DbSession,
    slug: ModelSlug,
) -> TTSModel:
    model: TTSModel | None = (await db.exec(select(TTSModel).where(TTSModel.slug == slug))).first()
    if not model:
        raise HTTPException(404, f"Model {slug!r} not found")
    return model


CurrentTTSModel = Annotated[TTSModel, Depends(get_model)]


async def get_voice(
    db: DbSession,
    model_slug: ModelSlug,
    voice_slug: VoiceSlug,
) -> Voice:
    voice: Voice | None = (
        await db.exec(select(Voice).join(TTSModel).where(Voice.slug == voice_slug, TTSModel.slug == model_slug))
    ).first()
    if not voice:
        raise HTTPException(404, f"Voice {voice_slug!r} not configured for model {model_slug!r}")
    return voice


async def get_block(
    document_id: UUID,
    block_id: int,
    db: DbSession,
    user: AuthenticatedUser,
) -> Block:
    block: Block | None = await db.get(
        Block,
        block_id,
        options=[selectinload("*")],
    )
    if not block or block.document_id != document_id:
        raise HTTPException(404, f"Block {block_id!r} not found in document {document_id!r}")

    if block.document.user_id != user.id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "cannot access block in another user's document")

    return block


async def get_block_variant(
    variant_hash: str,
    db: DbSession,
    user: AuthenticatedUser,
) -> BlockVariant:
    variant: BlockVariant | None = await db.get(
        BlockVariant,
        variant_hash,
        options=[selectinload(BlockVariant.block).selectinload(Block.document)],
    )
    if not variant:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"BlockVariant {variant_hash!r} not found")

    if variant.block.document.user_id != user.id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "cannot access block variant in another user's document")

    return variant


async def is_admin(user: Annotated[User, Depends(authenticate)]) -> bool:
    """Check if the authenticated user is an admin."""
    return user.server_metadata and user.server_metadata.is_admin


async def require_admin(is_admin: IsAdmin) -> None:
    """Require the authenticated user to be an admin."""
    if not is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")


async def get_or_create_user_credits(user_id: str, db: DbSession) -> UserCredits:
    user_credits = await db.get(UserCredits, user_id)
    if not user_credits:
        user_credits = UserCredits(
            user_id=user_id,
            balance=Decimal("0"),
            total_purchased=Decimal("0"),
            total_used=Decimal("0"),
        )
        db.add(user_credits)
    return user_credits


async def get_redis_client(request: Request) -> Redis:
    return request.app.state.redis_client


async def get_document_processor_manager(request: Request) -> DocumentProcessorManager:
    return request.app.state.document_processor_manager


RedisClient = Annotated[Redis, Depends(get_redis_client)]
DocumentProcessorManagerDep = Annotated[DocumentProcessorManager, Depends(get_document_processor_manager)]
AudioCache = Annotated[Cache, Depends(get_audio_cache)]
DocumentCache = Annotated[Cache, Depends(get_document_cache)]
TextSplitterDep = Annotated[TextSplitter, Depends(get_text_splitter)]
CurrentDoc = Annotated[Document, Depends(get_doc)]
CurrentVoice = Annotated[Voice, Depends(get_voice)]
CurrentBlock = Annotated[Block, Depends(get_block)]
CurrentBlockVariant = Annotated[BlockVariant, Depends(get_block_variant)]
AuthenticatedUser = Annotated[User, Depends(authenticate)]
IsAdmin = Annotated[bool, Depends(is_admin)]

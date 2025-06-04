from __future__ import annotations

from typing import Annotated, AsyncIterator, Callable
from uuid import UUID

from fastapi import Body, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.auth import authenticate
from yapit.gateway.cache import Cache, Caches, NoOpCache, SqliteCache
from yapit.gateway.config import Settings, get_settings
from yapit.gateway.db import create_session
from yapit.gateway.domain_models import Block, BlockVariant, Document, TTSModel, Voice
from yapit.gateway.redis_client import get_app_redis_client
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
    if audio_cache_type == Caches.NOOP.name.lower():
        return NoOpCache(settings.audio_cache_config)
    elif audio_cache_type == Caches.SQLITE.name.lower():
        return SqliteCache(settings.audio_cache_config)
    else:
        raise ValueError(f"Invalid audio cache type '{settings.audio_cache_type}' (noop, sqlite)")


def get_text_splitter(settings: SettingsDep) -> TextSplitter:
    splitter_type = settings.splitter_type.lower()
    if splitter_type == TextSplitters.DUMMY.name.lower():
        return DummySplitter(settings.splitter_config)
    elif splitter_type == TextSplitters.HIERARCHICAL.name.lower():
        return HierarchicalSplitter(settings.splitter_config)
    else:
        raise ValueError(f"Invalid TextSplitter type '{settings.splitter_type}' (dummy, hierarchical)")


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
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "cannot access block in another user's document",
        )

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
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"BlockVariant {variant_hash!r} not found",
        )

    if variant.block.document.user_id != user.id:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "cannot access block variant in another user's document",
        )

    return variant


RedisClient = Annotated[Redis, Depends(get_app_redis_client)]
AudioCache = Annotated[Cache, Depends(get_audio_cache)]
TextSplitterDep = Annotated[TextSplitter, Depends(get_text_splitter)]
CurrentDoc = Annotated[Document, Depends(get_doc)]
CurrentVoice = Annotated[Voice, Depends(get_voice)]
CurrentBlock = Annotated[Block, Depends(get_block)]
CurrentBlockVariant = Annotated[BlockVariant, Depends(get_block_variant)]
AuthenticatedUser = Annotated[User, Depends(authenticate)]

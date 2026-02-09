from __future__ import annotations

from pathlib import Path
from typing import Annotated, AsyncIterator
from uuid import UUID

import stripe
from fastapi import Depends, HTTPException, Request, status
from redis.asyncio import Redis
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.auth import authenticate
from yapit.gateway.cache import Cache, CacheConfig, Caches, SqliteCache
from yapit.gateway.config import Settings, get_settings
from yapit.gateway.db import create_session, get_or_404
from yapit.gateway.document.gemini import GeminiExtractor
from yapit.gateway.document.processing import ProcessorConfig
from yapit.gateway.domain_models import (
    Block,
    BlockVariant,
    Document,
    TTSModel,
    Voice,
)
from yapit.gateway.exceptions import ResourceNotFoundError
from yapit.gateway.stack_auth.users import User
from yapit.gateway.storage import ImageStorage, LocalImageStorage, R2ImageStorage

SettingsDep = Annotated[Settings, Depends(get_settings)]


def create_cache(cache_type: Caches, config: CacheConfig) -> Cache:
    """Create a new cache instance. Used during app startup."""
    match cache_type:
        case Caches.SQLITE:
            return SqliteCache(config)


def create_image_storage(settings: Settings) -> ImageStorage:
    """Create image storage backend based on settings."""
    match settings.image_storage_type:
        case "local":
            assert settings.images_dir, "IMAGES_DIR required for local storage"
            return LocalImageStorage(Path(settings.images_dir))
        case "r2":
            assert settings.r2_account_id, "R2_ACCOUNT_ID required for r2 storage"
            assert settings.r2_access_key_id, "R2_ACCESS_KEY_ID required for r2 storage"
            assert settings.r2_secret_access_key, "R2_SECRET_ACCESS_KEY required for r2 storage"
            assert settings.r2_bucket_name, "R2_BUCKET_NAME required for r2 storage"
            assert settings.r2_public_url, "R2_PUBLIC_URL required for r2 storage"
            return R2ImageStorage(
                account_id=settings.r2_account_id,
                access_key_id=settings.r2_access_key_id,
                secret_access_key=settings.r2_secret_access_key,
                bucket_name=settings.r2_bucket_name,
                public_url=settings.r2_public_url,
            )
        case _:
            raise ValueError(f"Unknown image storage type: {settings.image_storage_type}")


async def get_audio_cache(request: Request) -> Cache:
    return request.app.state.audio_cache


async def get_document_cache(request: Request) -> Cache:
    return request.app.state.document_cache


async def get_extraction_cache(request: Request) -> Cache:
    return request.app.state.extraction_cache


async def get_image_storage(request: Request) -> ImageStorage:
    return request.app.state.image_storage


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
    model = (await db.exec(select(TTSModel).where(TTSModel.slug == model_slug))).first()
    if not model:
        raise ResourceNotFoundError(TTSModel.__name__, model_slug)
    return model


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
) -> BlockVariant:
    return await get_or_404(db, BlockVariant, variant_hash)


async def get_redis_client(request: Request) -> Redis:
    return request.app.state.redis_client


async def get_ai_extractor_config(request: Request) -> ProcessorConfig | None:
    return request.app.state.ai_extractor_config


async def get_ai_extractor(request: Request) -> GeminiExtractor | None:
    return request.app.state.ai_extractor


def get_stripe_client(settings: SettingsDep) -> stripe.StripeClient | None:
    """Stripe client for billing operations. Returns None if billing is not configured."""
    if not settings.stripe_secret_key:
        return None
    return stripe.StripeClient(settings.stripe_secret_key)


RedisClient = Annotated[Redis, Depends(get_redis_client)]
AiExtractorConfigDep = Annotated[ProcessorConfig | None, Depends(get_ai_extractor_config)]
AiExtractorDep = Annotated[GeminiExtractor | None, Depends(get_ai_extractor)]
AudioCache = Annotated[Cache, Depends(get_audio_cache)]
DocumentCache = Annotated[Cache, Depends(get_document_cache)]
ExtractionCache = Annotated[Cache, Depends(get_extraction_cache)]
ImageStorageDep = Annotated[ImageStorage, Depends(get_image_storage)]
CurrentDoc = Annotated[Document, Depends(get_doc)]
CurrentVoice = Annotated[Voice, Depends(get_voice)]
CurrentBlock = Annotated[Block, Depends(get_block)]
CurrentBlockVariant = Annotated[BlockVariant, Depends(get_block_variant)]
AuthenticatedUser = Annotated[User, Depends(authenticate)]
StripeClient = Annotated[stripe.StripeClient | None, Depends(get_stripe_client)]

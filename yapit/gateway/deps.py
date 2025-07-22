from __future__ import annotations

from decimal import Decimal
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
from yapit.gateway.domain_models import (
    Block,
    BlockVariant,
    CreditTransaction,
    Document,
    TransactionStatus,
    TransactionType,
    TTSModel,
    UserCredits,
    Voice,
)
from yapit.gateway.exceptions import ResourceNotFoundError
from yapit.gateway.processors.document.manager import DocumentProcessorManager
from yapit.gateway.stack_auth.users import User
from yapit.gateway.text_splitter import (
    DummySplitter,
    HierarchicalSplitter,
    TextSplitter,
    TextSplitters,
)

SettingsDep = Annotated[Settings, Depends(get_settings)]


def _get_cache(cache_type: Caches, config: CacheConfig) -> Cache:
    match cache_type:
        case Caches.SQLITE:
            return SqliteCache(config)
        case _:
            raise ValueError(f"Invalid cache type {cache_type}")


def get_audio_cache(settings: SettingsDep) -> Cache:
    return _get_cache(settings.audio_cache_type, settings.audio_cache_config)


def get_document_cache(settings: SettingsDep) -> Cache:
    return _get_cache(settings.document_cache_type, settings.document_cache_config)


def get_text_splitter(settings: SettingsDep) -> TextSplitter:
    match settings.splitter_type:
        case TextSplitters.DUMMY:
            return DummySplitter(settings.splitter_config)
        case TextSplitters.HIERARCHICAL:
            return HierarchicalSplitter(settings.splitter_config)
        case _:
            raise ValueError(f"Invalid TextSplitter type {settings.splitter_type}")


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
        options=[selectinload(BlockVariant.block).selectinload(Block.document)],
    )

    if variant.block.document.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Cannot access block variant in another user's document"
        )
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


async def _get_or_create_user_credits_dep_helper(user: AuthenticatedUser, db: DbSession) -> UserCredits:
    return await get_or_create_user_credits(user.id, db)


async def ensure_admin_credits(
    user: AuthenticatedUser,
    user_credits: AuthenticatedUserCredits,
    db: DbSession,
    is_admin: IsAdmin,
    min_balance: Decimal = Decimal(1000),
    top_up_amount: Decimal = Decimal(10000),
) -> None:
    """Ensure admin users have sufficient credits by topping up if needed (for testing/development/self-hosting)."""
    if is_admin and user_credits.balance < min_balance:
        balance_before = user_credits.balance
        user_credits.balance += top_up_amount
        transaction = CreditTransaction(
            user_id=user.id,
            type=TransactionType.credit_bonus,
            status=TransactionStatus.completed,
            amount=top_up_amount,
            balance_before=balance_before,
            balance_after=user_credits.balance,
            description="Admin auto top-up",
        )
        db.add(transaction)
        await db.commit()


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
AuthenticatedUserCredits = Annotated[UserCredits, Depends(_get_or_create_user_credits_dep_helper)]

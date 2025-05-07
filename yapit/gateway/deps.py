from typing import Annotated, AsyncIterator, Callable
from uuid import UUID

from fastapi import Body, Depends, HTTPException, Path
from redis.asyncio import Redis
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.cache import Cache, CacheConfig, Caches, NoOpCache, SqliteCache
from yapit.gateway.config import get_settings
from yapit.gateway.db import SessionLocal
from yapit.gateway.domain_models import Block, BlockVariant, Document, TTSModel, Voice
from yapit.gateway.redis_client import get_redis
from yapit.gateway.text_splitter import (
    DummySplitter,
    HierarchicalSplitter,
    TextSplitter,
    TextSplitterConfig,
    TextSplitters,
)


class CacheDependency:
    def __init__(self, cache_type: str | None = None, config: CacheConfig | None = None):
        settings = get_settings()
        self.config = config or settings.cache_config
        self.type = cache_type or settings.cache_type.lower()

    def __call__(self) -> Cache:
        cache_class = {
            Caches.NOOP: NoOpCache,
            Caches.SQLITE: SqliteCache,
        }.get(self.type)
        if cache_class:
            return cache_class(self.config)
        raise ValueError(f"Invalid cache type: {self.type} - available: {', '.join([c.name for c in Caches])}.")


get_audio_cache = CacheDependency()


class TextSplitterDependency:
    def __init__(self, splitter_type: str | None = None, config: TextSplitterConfig | None = None):
        settings = get_settings()
        self.config = config or settings.splitter_config
        self.type = splitter_type or settings.splitter_type.lower()

    def __call__(self) -> TextSplitter:
        splitter_class = {
            TextSplitters.DUMMY: DummySplitter,
            TextSplitters.HIERARCHICAL: HierarchicalSplitter,
        }.get(self.type)
        if splitter_class:
            return splitter_class(self.config)
        raise ValueError(
            f"Invalid TextSplitter type: {self.type} - available : {', '.join([s.name for s in TextSplitters])}."
        )


get_text_splitter = TextSplitterDependency()


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db_session)]


async def get_doc(
    document_id: UUID,
    db: DbSession,
) -> Document:
    doc: Document | None = await db.get(Document, document_id)
    if not doc:
        raise HTTPException(404, f"Document {document_id!r} not found")
    return doc


def _get_param_extractor(name: str) -> Callable:
    """Helper to return a FastAPI dependency that fetches `name` from path/query or JSON."""

    async def extract(
        value: str | None = None, # from url path or query parameter
        body: dict | None = Body(None),  # from already-parsed JSON
    ) -> str:
        if value:
            return value
        if body and name in body:
            return body[name]
        raise HTTPException(422, f"{name} missing")

    extract.__name__ = f"extract_{name}"
    return extract


async def get_model(
    db: DbSession,
    slug: str = Depends(_get_param_extractor("model_slug")),
) -> TTSModel:
    model: TTSModel | None = (await db.exec(select(TTSModel).where(TTSModel.slug == slug))).first()
    if not model:
        raise HTTPException(404, f"Model {slug!r} not found")
    return model


CurrentTTSModel = Annotated[TTSModel, Depends(get_model)]


async def get_voice(
    db: DbSession,
    model: CurrentTTSModel,
    slug: str = Depends(_get_param_extractor("voice_slug")),
) -> Voice:
    voice: Voice | None = (await db.exec(select(Voice).where(Voice.slug == slug, Voice.model_id == model.id))).first()
    if not voice:
        raise HTTPException(404, f"Voice {slug!r} not configured for model {model.slug!r}")
    return voice


async def get_block(
    document_id: UUID,
    block_id: int,
    db: DbSession,
) -> Block:
    block: Block | None = await db.get(Block, block_id)
    if not block or block.document_id != document_id:
        raise HTTPException(404, f"Block {block_id!r} not found in document {document_id!r}")
    return block


async def get_block_variant(
    variant_hash: str,
    db: DbSession,
) -> BlockVariant:
    variant: BlockVariant | None = await db.get(BlockVariant, variant_hash)
    if not variant:
        raise HTTPException(404, f"BlockVariant {variant_hash!r} not found")
    return variant


RedisClient = Annotated[Redis, Depends(get_redis)]
AudioCache = Annotated[Cache, Depends(get_audio_cache)]
TextSplitterDep = Annotated[TextSplitter, Depends(get_text_splitter)]
CurrentDoc = Annotated[Document, Depends(get_doc)]
CurrentVoice = Annotated[Voice, Depends(get_voice)]
CurrentBlock = Annotated[Block, Depends(get_block)]
CurrentBlockVariant = Annotated[BlockVariant, Depends(get_block_variant)]

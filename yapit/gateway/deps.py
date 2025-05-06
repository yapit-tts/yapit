from typing import AsyncIterator, Callable
from uuid import UUID

from fastapi import Body, Depends, HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.db import SessionLocal
from yapit.gateway.domain_models import Block, BlockVariant, Document, Model, Voice


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def get_doc(
    document_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> Document:
    doc: Document | None = await db.get(Document, document_id)
    if not doc:
        raise HTTPException(404, f"Document {document_id!r} not found")
    return doc


def _get_param_extractor(name: str) -> Callable:
    """Helper to return a FastAPI dependency that fetches `name` from path/query or JSON."""

    async def extract(
        value: str | None = None,  # path or ?name=
        body: dict | None = Body(None),  # already-parsed JSON
    ) -> str:
        if value:
            return value
        if body and name in body:
            return body[name]
        raise HTTPException(422, f"{name} missing")

    extract.__name__ = f"extract_{name}"
    return extract


async def get_model(
    slug: str = Depends(_get_param_extractor("model_slug")),
    db: AsyncSession = Depends(get_db_session),
) -> Model:
    model: Model | None = (await db.exec(select(Model).where(Model.slug == slug))).first()
    if not model:
        raise HTTPException(404, f"Model {slug!r} not found")
    return model


async def get_voice(
    slug: str = Depends(_get_param_extractor("voice_slug")),
    model: Model = Depends(get_model),
    db: AsyncSession = Depends(get_db_session),
) -> Voice:
    voice: Voice | None = (await db.exec(select(Voice).where(Voice.slug == slug, Voice.model_id == model.id))).first()
    if not voice:
        raise HTTPException(404, f"Voice {slug!r} not configured for model {model.slug!r}")
    return voice


async def get_block(
    document_id: UUID,
    block_id: int,
    db: AsyncSession = Depends(get_db_session),
) -> Block:
    block: Block | None = await db.get(Block, block_id)
    if not block or block.document_id != document_id:
        raise HTTPException(404, f"Block {block_id!r} not found in document {document_id!r}")
    return block


async def get_block_variant(
    variant_hash: str,
    db: AsyncSession = Depends(get_db_session),
) -> BlockVariant:
    variant: BlockVariant | None = await db.get(BlockVariant, variant_hash)
    if not variant:
        raise HTTPException(404, f"BlockVariant {variant_hash!r} not found")
    return variant

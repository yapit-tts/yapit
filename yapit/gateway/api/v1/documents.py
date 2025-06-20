from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, HttpUrl
from sqlmodel import func, select
from starlette.concurrency import run_in_threadpool

from yapit.gateway.auth import User, authenticate
from yapit.gateway.deps import AuthenticatedUser, CurrentDoc, DbSession, TextSplitterDep, get_doc
from yapit.gateway.domain_models import Block, Document, SourceType
from yapit.gateway.utils import estimate_duration_ms

router = APIRouter(prefix="/v1/documents", tags=["Documents"])

# how many blocks to embed in create-doc response
_PREVIEW_LIMIT = 20


class DocumentCreateRequest(BaseModel):
    """Payload for creating a document.

    Attributes:
        source_type: Where the text comes from
        text_content: Raw text when source_type == "paste".
        source_ref: URL or filename (for url and upload types).
    """

    source_type: SourceType
    text_content: str | None = None
    source_ref: HttpUrl | str | None = None


class BlockRead(BaseModel):
    id: int
    idx: int
    text: str
    est_duration_ms: int | None = None


class DocumentCreateResponse(BaseModel):
    document_id: UUID
    num_blocks: int
    est_duration_ms: int
    blocks: list[BlockRead]


class BlockPage(BaseModel):
    total: int
    items: list[BlockRead]
    next_offset: int | None


@router.post(
    "",
    response_model=DocumentCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_document(
    req: DocumentCreateRequest,
    db: DbSession,
    splitter: TextSplitterDep,
    user: AuthenticatedUser,
) -> DocumentCreateResponse:
    """Create a new Document from pasted text.

    TODO URL and file‑upload branches are stubbed (501 Not Implemented).

    Returns:
        Metadata about the created document (ID, block count, est. duration).
    """
    # obtain raw text
    if req.source_type == "paste":
        if not req.text_content or not req.text_content.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="text_content must be provided and non‑empty for paste uploads",
            )
        text = req.text_content.strip()
    elif req.source_type == "url":
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="URL parsing not implemented yet")
    elif req.source_type == "upload":
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="File uploads not implemented yet")
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid source_type")
    if not text:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error: text is missing or invalid",
        )

    # persist Document
    doc = Document(
        user_id=user.id,
        source_type=req.source_type,
        source_ref=req.source_ref,
        original_text=text,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    # split into Blocks
    try:
        text_blocks = await run_in_threadpool(splitter.split, text=text)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Text splitting failed: {exc}"
        ) from exc
    est_total_ms = 0
    blocks: list[Block] = []
    for idx, text_block in enumerate(text_blocks):
        dur = estimate_duration_ms(text_block)
        est_total_ms += dur
        blocks.append(Block(document_id=doc.id, idx=idx, text=text_block, est_duration_ms=dur))
    db.add_all(blocks)
    await db.commit()

    return DocumentCreateResponse(
        document_id=doc.id,
        num_blocks=len(blocks),
        est_duration_ms=est_total_ms,
        blocks=[
            BlockRead(id=b.id, idx=b.idx, text=b.text, est_duration_ms=b.est_duration_ms)
            for b in blocks[:_PREVIEW_LIMIT]
        ],
    )


@router.get("/{document_id}/blocks", response_model=BlockPage, dependencies=[Depends(get_doc)])
async def list_blocks(
    document_id: UUID,
    db: DbSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> BlockPage:
    total = (await db.exec(select(func.count()).select_from(Block).where(Block.document_id == document_id))).one()
    rows = await db.exec(
        select(Block).where(Block.document_id == document_id).order_by(Block.idx).offset(offset).limit(limit)
    )
    items = [BlockRead(id=b.id, idx=b.idx, text=b.text, est_duration_ms=b.est_duration_ms) for b in rows.all()]

    next_offset = offset + limit if offset + limit < total else None
    return BlockPage(total=total, items=items, next_offset=next_offset)


class DocumentMeta(BaseModel):
    document_id: UUID
    created: datetime
    has_filtered: bool
    last_applied_filter_config: dict | None


@router.get("/{document_id}", response_model=DocumentMeta)
async def read_document_meta(doc: CurrentDoc) -> DocumentMeta:
    return DocumentMeta(
        document_id=doc.id,
        created=doc.created,
        has_filtered=doc.filtered_text is not None,
        last_applied_filter_config=doc.last_applied_filter_config,
    )

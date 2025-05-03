import math
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, HttpUrl
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.auth import get_current_user_id
from yapit.gateway.db import get_db
from yapit.gateway.domain_models import Block, Document, SourceType
from yapit.gateway.text_splitter import TextSplitter, get_text_splitter
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
    doc_id: UUID
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
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    splitter: TextSplitter = Depends(get_text_splitter),
) -> DocumentCreateResponse:
    """Create a new Document from pasted text.

    TODO URL and file‑upload branches are stubbed (501 Not Implemented).

    Returns:
        Metadata about the created document (ID, block count, est. duration).
    """
    # --- obtain raw text
    if req.source_type == "paste":
        if not (req.text_content and req.text_content.strip()):
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

    # --- Persist Document
    doc = Document(
        user_id=user_id,
        source_type=req.source_type,
        source_ref=req.source_ref,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    # --- Split into blocks
    try:
        text_blocks = splitter.split(text)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Text splitting failed: {exc}",
        ) from exc

    est_total_ms = 0.0
    blocks: list[Block] = []
    for idx, text_block in enumerate(text_blocks):
        dur = estimate_duration_ms(text_block)
        est_total_ms += dur
        blocks.append(Block(document_id=doc.id, idx=idx, text=text_block, est_duration_ms=dur))

    if blocks:
        db.add_all(blocks)
        await db.commit()

    preview = [
        BlockRead(id=b.id, idx=b.idx, text=b.text, est_duration_ms=b.est_duration_ms) for b in blocks[:_PREVIEW_LIMIT]
    ]

    return DocumentCreateResponse(
        doc_id=doc.id,
        num_blocks=len(blocks),
        est_duration_ms=est_total_ms,
        blocks=preview,
    )


@router.get("/{document_id}/blocks", response_model=BlockPage)
async def list_blocks(
    document_id: UUID,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    db: AsyncSession = Depends(get_db),
) -> BlockPage:
    if not await db.get(Document, document_id):
        raise HTTPException(status_code=404, detail="document not found")

    # nit: fix type err
    total = (await db.exec(select(func.count()).select_from(Block).where(Block.document_id == document_id))).one()
    # nit: fix type err
    rows = await db.exec(
        select(Block).where(Block.document_id == document_id).order_by(Block.idx).offset(offset).limit(limit)
    )
    items = [BlockRead(id=b.id, idx=b.idx, text=b.text, est_duration_ms=b.est_duration_ms) for b in rows.all()]

    next_offset = offset + limit if offset + limit < total else None
    return BlockPage(total=total, items=items, next_offset=next_offset)


# --- Helpers (future work)
async def extract_text_from_url(url: HttpUrl) -> str:
    raise NotImplementedError("URL text extraction not yet implemented")


async def extract_text_from_upload(file: bytes) -> str:
    raise NotImplementedError("File upload text extraction not yet implemented")

import math
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, HttpUrl
from sqlmodel.ext.asyncio.session import AsyncSession

from gateway.db import get_db
from gateway.domain.models import Block, Document
from gateway.text_splitter import TextSplitter, get_text_splitter

router = APIRouter(prefix="/v1/documents", tags=["Documents"])


class DocumentCreateRequest(BaseModel):
    source_type: Literal["paste", "url", "upload"]
    text_content: str | None = None
    source_ref: HttpUrl | str | None = None


class DocumentCreateResponse(BaseModel):
    document_id: UUID
    num_blocks: int
    est_duration_ms: float


ANON_USER_ID = "anonymous_user"  # Seeded once during migrations / tests # TODO move to config?


@router.post(
    "",
    response_model=DocumentCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_document(
    req: DocumentCreateRequest,
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
        user_id=ANON_USER_ID,  # TODO replace with actual user ID
        source_type=req.source_type,
        source_ref=req.source_ref,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    # --- Split into blocks
    try:
        pieces = splitter.split(text)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Text splitting failed: {exc}",
        ) from exc

    est_total = 0.0
    blocks: list[Block] = []
    chars_per_second = 15.0  # TODO measure & evaluate

    for idx, piece in enumerate(pieces):
        if not piece:
            continue
        dur = math.ceil(len(piece) / chars_per_second * 1000)  # ms
        est_total += dur
        blocks.append(Block(document_id=doc.id, idx=idx, text=piece, est_duration_ms=dur))

    if blocks:
        db.add_all(blocks)
        await db.commit()

    return DocumentCreateResponse(
        document_id=doc.id,
        num_blocks=len(blocks),
        est_duration_ms=est_total,
    )


# --- Helpers (future work)
async def extract_text_from_url(url: HttpUrl) -> str:
    raise NotImplementedError("URL text extraction not yet implemented")


async def extract_text_from_upload(file: bytes) -> str:
    raise NotImplementedError("File upload text extraction not yet implemented")

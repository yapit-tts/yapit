"""AI extraction through the API: what the precheck refuses, what the extractor is asked for, what gets billed."""

from collections.abc import AsyncIterator
from unittest.mock import patch

import pymupdf
import pytest
from sqlmodel import select

from yapit.gateway.api.v1.documents import DocumentPrepareResponse, ExtractionAcceptedResponse
from yapit.gateway.auth import authenticate, authenticate_optional
from yapit.gateway.document.types import ExtractedPage, PageResult, ProcessorConfig
from yapit.gateway.domain_models import UsageLog
from yapit.gateway.reservations import get_reservation
from yapit.gateway.stack_auth.users import User

from .test_documents import poll_for_document

AI_CONFIG = ProcessorConfig(
    slug="fake-ai",
    supported_mime_types=frozenset({"application/pdf"}),
    max_pages=100,
    max_file_size=10 * 1024 * 1024,
    is_paid=True,
    output_token_multiplier=1,
    extraction_cache_prefix="fake-ai:v1",
)


class FakeExtractor:
    """Yields one page of markdown per requested page and remembers what it was asked for."""

    def __init__(self) -> None:
        self.requests: list[list[int]] = []

    async def extract(
        self,
        content: bytes,
        content_type: str,
        content_hash: str,
        pages: list[int] | None = None,
        user_id: str | None = None,
        cancel_key: str | None = None,
        prompt_override: str | None = None,
    ) -> AsyncIterator[PageResult]:
        self.requests.append(sorted(pages) if pages else [])
        for page_idx in pages or []:
            yield PageResult(
                page_idx=page_idx,
                page=ExtractedPage(markdown=f"Extracted page {page_idx}", images=[]),
                input_tokens=100,
                output_tokens=50,
                thoughts_tokens=0,
                is_fallback=False,
                cancelled=False,
            )

    @property
    def model(self) -> str:
        return "fake"


@pytest.fixture
def ai_extractor(app):
    extractor = FakeExtractor()
    app.state.ai_extractor_config = AI_CONFIG
    app.state.ai_extractor = extractor
    yield extractor
    app.state.ai_extractor_config = None
    app.state.ai_extractor = None


@pytest.fixture
def as_subscribed_user(app, subscribed_user):
    user = User(id=subscribed_user["user_id"], is_anonymous=False)
    app.dependency_overrides[authenticate] = lambda: user
    app.dependency_overrides[authenticate_optional] = lambda: user
    yield user
    del app.dependency_overrides[authenticate]
    del app.dependency_overrides[authenticate_optional]


def _pdf(pages: int) -> bytes:
    doc = pymupdf.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 72), f"Page {i} text. " * 10)
    return doc.tobytes()


async def _upload(client, pages: int = 3) -> DocumentPrepareResponse:
    r = await client.post("/v1/documents/prepare/upload", files={"file": ("book.pdf", _pdf(pages), "application/pdf")})
    assert r.status_code == 200
    return DocumentPrepareResponse.model_validate(r.json())


async def _cache_pages(app, content_hash: str, page_indices: list[int]) -> None:
    for idx in page_indices:
        await app.state.extraction_cache.store(
            AI_CONFIG.extraction_cache_key(content_hash, idx),
            ExtractedPage(markdown=f"Cached page {idx}", images=[]).model_dump_json().encode(),
        )


async def _create_with_ai(client, prepared: DocumentPrepareResponse) -> str:
    """Create with AI, wait for the background extraction, return the document's text."""
    r = await client.post("/v1/documents/document", json={"hash": prepared.hash, "ai_transform": True})
    assert r.status_code == 202, r.text
    accepted = ExtractionAcceptedResponse.model_validate(r.json())
    status = await poll_for_document(
        client, accepted.extraction_id, accepted.content_hash, list(range(prepared.metadata.total_pages))
    )
    assert status.document_id, status.error
    r = await client.get(f"/v1/documents/{status.document_id}")
    assert r.status_code == 200
    return r.json()["original_text"]


@pytest.mark.asyncio
async def test_no_balance_is_refused_before_the_document_is_opened(client, as_test_user, ai_extractor):
    prepared = await _upload(client)

    # The estimate is the expensive part; a zero balance must never reach it
    with patch("yapit.gateway.api.v1.documents.estimate_document_tokens", side_effect=AssertionError("estimated")):
        r = await client.post("/v1/documents/document", json={"hash": prepared.hash, "ai_transform": True})

    assert r.status_code == 402
    assert ai_extractor.requests == []


@pytest.mark.asyncio
async def test_partly_cached_document_extracts_and_bills_only_the_uncached_pages(
    client, app, session, as_subscribed_user, ai_extractor
):
    prepared = await _upload(client, pages=3)
    await _cache_pages(app, prepared.content_hash, [1])

    text = await _create_with_ai(client, prepared)

    assert ai_extractor.requests == [[0, 2]]
    assert "Cached page 1" in text
    assert "Extracted page 0" in text

    billed = (await session.exec(select(UsageLog).where(UsageLog.user_id == as_subscribed_user.id))).all()
    assert sorted(row.details["page_idx"] for row in billed) == [0, 2]
    assert await get_reservation(app.state.redis_client, as_subscribed_user.id, prepared.content_hash) is None


@pytest.mark.asyncio
async def test_fully_cached_document_needs_no_balance(client, app, session, as_test_user, ai_extractor):
    """as_test_user has no subscription, so any estimate would be refused: none must run."""
    prepared = await _upload(client, pages=2)
    await _cache_pages(app, prepared.content_hash, [0, 1])

    text = await _create_with_ai(client, prepared)

    assert ai_extractor.requests == []
    assert "Cached page 0" in text
    assert (await session.exec(select(UsageLog))).all() == []

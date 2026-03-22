"""Tests for delete_documents_with_images shared function."""

import pytest

from yapit.gateway.api.v1.documents import delete_documents_with_images
from yapit.gateway.db import create_session
from yapit.gateway.domain_models import Document
from yapit.gateway.storage import LocalImageStorage


@pytest.fixture
def image_storage(tmp_path):
    return LocalImageStorage(tmp_path)


def _make_doc(user_id: str = "test-user", content_hash: str | None = None, **kwargs) -> Document:
    return Document(
        user_id=user_id,
        title="Test",
        original_text="hello",
        structured_content="{}",
        content_hash=content_hash,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_deletes_documents_and_returns_count(session, image_storage):
    docs = [_make_doc(), _make_doc()]
    for doc in docs:
        session.add(doc)
    await session.commit()

    count = await delete_documents_with_images(docs, session, image_storage)
    await session.commit()

    assert count == 2


@pytest.mark.asyncio
async def test_empty_list_returns_zero(session, image_storage):
    assert await delete_documents_with_images([], session, image_storage) == 0


@pytest.mark.asyncio
async def test_cleans_up_orphaned_images(session, image_storage, tmp_path):
    content_hash = "abc123"
    doc = _make_doc(content_hash=content_hash)
    session.add(doc)
    await session.commit()

    # Create image directory for this content hash
    img_dir = tmp_path / content_hash
    img_dir.mkdir()
    (img_dir / "figure_0.png").write_bytes(b"fake image")

    await delete_documents_with_images([doc], session, image_storage)
    await session.commit()

    assert not img_dir.exists()


@pytest.mark.asyncio
async def test_preserves_images_still_referenced(session, image_storage, tmp_path):
    content_hash = "shared_hash"
    doc_to_delete = _make_doc(user_id="user-a", content_hash=content_hash)
    doc_to_keep = _make_doc(user_id="user-b", content_hash=content_hash)
    session.add(doc_to_delete)
    session.add(doc_to_keep)
    await session.commit()

    img_dir = tmp_path / content_hash
    img_dir.mkdir()
    (img_dir / "figure_0.png").write_bytes(b"fake image")

    await delete_documents_with_images([doc_to_delete], session, image_storage)
    await session.commit()

    assert img_dir.exists()
    assert (img_dir / "figure_0.png").exists()


@pytest.mark.asyncio
async def test_does_not_commit(session, image_storage):
    """Caller controls the transaction — the function only flushes."""
    doc = _make_doc()
    session.add(doc)
    await session.commit()
    doc_id = doc.id

    await delete_documents_with_images([doc], session, image_storage)
    # Roll back instead of committing — doc should still exist in DB
    await session.rollback()

    # Verify with a fresh session to avoid identity map issues
    async with create_session() as fresh:
        refreshed = await fresh.get(Document, doc_id)
        assert refreshed is not None

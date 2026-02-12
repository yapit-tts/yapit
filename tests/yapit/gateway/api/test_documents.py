import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from yapit.gateway.api.v1.documents import (
    DocumentCreateResponse,
    DocumentPrepareResponse,
    ExtractionAcceptedResponse,
    ExtractionStatusResponse,
    _get_endpoint_type_from_content_type,
)

FIXTURES_DIR = Path("tests/fixtures/documents")


async def poll_for_document(
    client,
    extraction_id: str,
    content_hash: str,
    pages: list[int],
    timeout: float = 5.0,
) -> ExtractionStatusResponse:
    """Poll /extraction/status until document_id or error appears."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        r = await client.post(
            "/v1/documents/extraction/status",
            json={
                "extraction_id": extraction_id,
                "content_hash": content_hash,
                "ai_transform": False,
                "pages": pages,
            },
        )
        status_data = ExtractionStatusResponse.model_validate(r.json())
        if status_data.document_id or status_data.error:
            return status_data
        await asyncio.sleep(0.05)
    raise TimeoutError(f"Extraction did not complete within {timeout}s")


@pytest.mark.asyncio
async def test_create_document(client):
    text = "Sentence one. Sentence two."

    r = await client.post(
        "/v1/documents/text",
        json={"content": text},
    )
    assert r.status_code == 201

    doc = DocumentCreateResponse.model_validate(r.json())

    blocks = (await client.get(f"/v1/documents/{doc.id}/blocks")).json()
    assert len(blocks) == 1
    assert blocks[0]["text"] == text


@pytest.mark.asyncio
async def test_prepare_and_create_document_from_url(client, as_test_user, session):
    """Test complete flow: URL → prepare → create document (async extraction via PyMuPDF)."""
    mock_content = (FIXTURES_DIR / "minimal.pdf").read_bytes()
    mock_content_type = "application/pdf"

    with patch("yapit.gateway.api.v1.documents.download_document") as mock_download:
        mock_download.return_value = (mock_content, mock_content_type)

        # Step 1: Prepare document from URL
        prepare_response = await client.post("/v1/documents/prepare", json={"url": "https://example.com/test.pdf"})

        assert prepare_response.status_code == 200
        prepare_data = DocumentPrepareResponse.model_validate(prepare_response.json())

        assert prepare_data.metadata.content_type == "application/pdf"
        assert prepare_data.metadata.total_pages >= 1
        assert prepare_data.endpoint == "document"
        assert prepare_data.uncached_pages == set()

        # Step 2: Submit document for extraction (returns 202)
        create_response = await client.post(
            "/v1/documents/document",
            json={
                "hash": prepare_data.hash,
                "title": "Test Document",
                "ai_transform": False,
            },
        )

        assert create_response.status_code == 202
        accepted = ExtractionAcceptedResponse.model_validate(create_response.json())

        # Step 3: Poll for completion
        status_data = await poll_for_document(client, accepted.extraction_id, accepted.content_hash, pages=[0])
        assert status_data.document_id is not None
        assert status_data.error is None


@pytest.mark.asyncio
async def test_prepare_caching(client, as_test_user):
    """Test that prepare endpoint uses cache on repeated calls."""
    mock_content = b"Test content"

    with patch("yapit.gateway.api.v1.documents.download_document") as mock_download:
        mock_download.return_value = (mock_content, "text/plain")

        # First call - should download
        response1 = await client.post("/v1/documents/prepare", json={"url": "https://example.com/cached.txt"})
        assert response1.status_code == 200
        assert mock_download.call_count == 1

        # Second call - should use cache
        response2 = await client.post("/v1/documents/prepare", json={"url": "https://example.com/cached.txt"})
        assert response2.status_code == 200
        assert mock_download.call_count == 1  # Not called again

        # Should return same hash
        data1 = DocumentPrepareResponse.model_validate(response1.json())
        data2 = DocumentPrepareResponse.model_validate(response2.json())
        assert data1.hash == data2.hash


@pytest.mark.asyncio
async def test_upload_and_create_document(client, as_test_user):
    """Test complete flow: file upload → prepare → create document."""
    # Step 1: Upload file
    file_content = b"Uploaded test content"
    files = {"file": ("test.txt", file_content, "text/plain")}

    upload_response = await client.post("/v1/documents/prepare/upload", files=files)

    assert upload_response.status_code == 200
    upload_data = DocumentPrepareResponse.model_validate(upload_response.json())

    assert upload_data.metadata.content_type == "text/plain"
    assert upload_data.metadata.file_name == "test.txt"
    assert upload_data.metadata.file_size == len(file_content)
    assert upload_data.endpoint == "document"


@pytest.mark.asyncio
async def test_document_create_invalid_page_numbers(client, as_test_user):
    """Test validation of page numbers when creating a document."""
    mock_content = b"fake pdf"

    with (
        patch("yapit.gateway.api.v1.documents.download_document") as mock_download,
        patch("yapit.gateway.api.v1.documents._extract_document_info") as mock_extract,
    ):
        mock_download.return_value = (mock_content, "application/pdf")
        mock_extract.return_value = (3, "Test PDF")  # 3 pages

        # First prepare the document
        prepare_response = await client.post(
            "/v1/documents/prepare",
            json={"url": "https://example.com/test.pdf"},
        )
        assert prepare_response.status_code == 200
        prepare_data = prepare_response.json()

        # Try to create document with invalid pages
        create_response = await client.post(
            "/v1/documents/document",
            json={
                "hash": prepare_data["hash"],
                "title": "Test Document",
                "ai_transform": False,
                "pages": [1, 5, 10],  # Pages 5 and 10 don't exist (0-indexed, so valid are 0,1,2)
            },
        )

        assert create_response.status_code == 422
        assert "Invalid page numbers: [5, 10]" in create_response.json()["detail"]
        assert "Document has 3 pages" in create_response.json()["detail"]


@pytest.mark.parametrize(
    "content_type,expected",
    [
        # HTML variations - all should be "website"
        ("text/html", "website"),
        ("TEXT/HTML", "website"),
        ("text/html; charset=utf-8", "website"),
        ("text/html;charset=UTF-8", "website"),
        ("text/html; boundary=something", "website"),
        ("text/html; charset=utf-8; boundary=test", "website"),
        ('text/html; charset="utf-8; tricky"', "website"),
        # XHTML
        ("application/xhtml+xml", "website"),
        ("application/xhtml+xml; charset=utf-8", "website"),
        # Documents
        ("text/plain", "document"),
        ("text/plain; charset=utf-8", "document"),
        ("text/markdown", "document"),
        ("text/x-markdown", "document"),
        ("application/pdf", "document"),
        ("application/pdf; version=1.7", "document"),
        ("image/png", "document"),
        ("image/jpeg", "document"),
        ("application/json", "document"),
        ("application/xml", "document"),  # Generic XML is a document
        # Edge cases
        (None, "document"),
        ("", "document"),
        ("malformed/type", "document"),
    ],
)
def test_content_type_detection(content_type, expected):
    """Test that content type detection properly handles MIME type parameters."""
    assert _get_endpoint_type_from_content_type(content_type) == expected


@pytest.mark.parametrize(
    "content_type",
    [
        "text/html; charset=utf-8",
        "text/html;charset=UTF-8",
        "text/html; charset=ISO-8859-1",
    ],
)
@pytest.mark.asyncio
async def test_prepare_detects_html_with_charset_as_website(client, as_test_user, content_type):
    """Test that HTML pages with charset parameters are correctly detected as websites."""
    mock_html = b"<!DOCTYPE html><html><body>Test</body></html>"

    with patch("yapit.gateway.api.v1.documents.download_document") as mock_download:
        mock_download.return_value = (mock_html, content_type)

        response = await client.post("/v1/documents/prepare", json={"url": "https://example.com/page.html"})

        assert response.status_code == 200
        data = DocumentPrepareResponse.model_validate(response.json())
        assert data.endpoint == "website"
        assert data.metadata.content_type == content_type


@pytest.mark.asyncio
async def test_prepare_website_returns_empty_uncached_pages(client, as_test_user):
    """Test that preparing a website always returns empty uncached pages."""
    mock_html = b"<!DOCTYPE html><html><body>Test</body></html>"

    with patch("yapit.gateway.api.v1.documents.download_document") as mock_download:
        mock_download.return_value = (mock_html, "text/html")

        response = await client.post("/v1/documents/prepare", json={"url": "https://example.com/page.html"})
        assert response.status_code == 200
        data = DocumentPrepareResponse.model_validate(response.json())
        assert data.endpoint == "website"
        assert data.uncached_pages == set()


# Position update tests


@pytest.mark.asyncio
async def test_update_position(client, as_test_user):
    """Test updating document playback position."""
    # Create a document first
    r = await client.post("/v1/documents/text", json={"content": "Test content for position"})
    assert r.status_code == 201
    doc = DocumentCreateResponse.model_validate(r.json())

    # Update position
    r = await client.patch(f"/v1/documents/{doc.id}/position", json={"block_idx": 5})
    assert r.status_code == 200
    assert r.json() == {"ok": True}

    # Verify position was saved
    r = await client.get(f"/v1/documents/{doc.id}")
    assert r.status_code == 200
    assert r.json()["last_block_idx"] == 5
    assert r.json()["last_played_at"] is not None


@pytest.mark.asyncio
async def test_update_position_not_found(client, as_test_user):
    """Test updating position for non-existent document."""
    r = await client.patch(
        "/v1/documents/00000000-0000-0000-0000-000000000000/position",
        json={"block_idx": 0},
    )
    assert r.status_code == 404

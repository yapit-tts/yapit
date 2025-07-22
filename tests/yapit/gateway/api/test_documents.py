from unittest.mock import patch

import pytest

from yapit.gateway.api.v1.documents import DocumentCreateResponse, DocumentPrepareResponse


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
    """Test complete flow: URL → prepare → create document."""
    # Mock the download to avoid real network calls
    mock_content = b"Test document content"
    mock_content_type = "text/plain"

    with patch("yapit.gateway.api.v1.documents._download_document") as mock_download:
        mock_download.return_value = (mock_content, mock_content_type)

        # Step 1: Prepare document from URL
        prepare_response = await client.post("/v1/documents/prepare", json={"url": "https://example.com/test.txt"})

        assert prepare_response.status_code == 200
        prepare_data = DocumentPrepareResponse.model_validate(prepare_response.json())

        assert prepare_data.metadata.content_type == "text/plain"
        assert prepare_data.metadata.total_pages == 1
        assert prepare_data.endpoint == "document"  # Not HTML, so not "website"
        assert prepare_data.credit_cost is None  # No OCR processor requested

        # Step 2: Try to create document (will fail without processor)
        create_response = await client.post(
            "/v1/documents/document",
            json={
                "hash": prepare_data.hash,
                "title": "Test Document",
                "processor_slug": "markitdown",
                "pages": None,  # Process all pages
            },
        )

        # Should fail because no processors are loaded in unit test config
        if create_response.status_code != 404:
            print(f"Status: {create_response.status_code}, Body: {create_response.json()}")
        assert create_response.status_code == 404


@pytest.mark.asyncio
async def test_prepare_caching(client, as_test_user):
    """Test that prepare endpoint uses cache on repeated calls."""
    mock_content = b"Test content"

    with patch("yapit.gateway.api.v1.documents._download_document") as mock_download:
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
async def test_prepare_invalid_page_numbers(client, as_test_user):
    """Test validation of page numbers in prepare."""
    mock_content = b"fake pdf"

    with (
        patch("yapit.gateway.api.v1.documents._download_document") as mock_download,
        patch("yapit.gateway.api.v1.documents._extract_document_info") as mock_extract,
    ):
        mock_download.return_value = (mock_content, "application/pdf")
        mock_extract.return_value = (3, "Test PDF")  # 3 pages

        # Request invalid pages
        response = await client.post(
            "/v1/documents/prepare",
            json={
                "url": "https://example.com/test.pdf",
                "pages": [1, 5, 10],  # Pages 5 and 10 don't exist
            },
        )

        assert response.status_code == 422
        assert "Invalid page numbers: [5, 10]" in response.json()["detail"]
        assert "Document has 3 pages" in response.json()["detail"]

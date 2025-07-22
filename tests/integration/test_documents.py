import pytest

from yapit.gateway.api.v1.documents import DocumentCreateResponse, DocumentPrepareResponse
from yapit.gateway.domain_models import Block


@pytest.mark.asyncio
async def test_create_text_document_full_flow(admin_client):
    """Test creating and retrieving a text document."""
    response = await admin_client.post(
        "/v1/documents/text", json={"content": "This is an integration test document.", "title": "Integration Test"}
    )

    assert response.status_code == 201
    doc_data = DocumentCreateResponse.model_validate(response.json())

    # Retrieve the document
    doc_response = await admin_client.get(f"/v1/documents/{doc_data.id}")
    assert doc_response.status_code == 200

    # Get blocks
    blocks_response = await admin_client.get(f"/v1/documents/{doc_data.id}/blocks")
    assert blocks_response.status_code == 200
    blocks = [Block.model_validate(b) for b in blocks_response.json()]
    assert len(blocks) == 1
    assert blocks[0].text == "This is an integration test document."


@pytest.mark.asyncio
async def test_prepare_and_process_with_markitdown(admin_client):
    """Test document preparation and processing with markitdown (free processor)."""
    # Prepare from URL
    prepare_response = await admin_client.post(
        "/v1/documents/prepare",
        json={"url": "https://www.example.com"},  # Real URL
    )

    assert prepare_response.status_code == 200
    prepare_data = DocumentPrepareResponse.model_validate(prepare_response.json())

    assert prepare_data.endpoint == "website"  # HTML content
    assert prepare_data.credit_cost is None  # No cost calculation for websites

    # Create document
    create_response = await admin_client.post(
        "/v1/documents/website", json={"hash": prepare_data.hash, "title": "Example Website"}
    )

    assert create_response.status_code == 201


@pytest.mark.asyncio
@pytest.mark.mistral
async def test_ocr_with_mistral_and_billing(admin_client):
    """Test OCR processing with Mistral API and admin billing."""
    # Upload test PDF with unique metadata to avoid cache hits
    import time

    import pymupdf

    with open("tests/fixtures/documents/minimal.pdf", "rb") as f:
        original_content = f.read()

    # Modify metadata to make it unique
    doc = pymupdf.open(stream=original_content)
    doc.metadata["Subject"] = f"Test run {time.time()}"
    unique_pdf_content = doc.tobytes()
    doc.close()

    files = {"file": ("minimal.pdf", unique_pdf_content, "application/pdf")}

    upload_response = await admin_client.post(
        "/v1/documents/prepare/upload", files=files, params={"processor_slug": "mistral-ocr"}
    )

    assert upload_response.status_code == 200
    upload_data = DocumentPrepareResponse.model_validate(upload_response.json())

    # Should show credit cost
    assert upload_data.credit_cost is not None
    assert float(upload_data.credit_cost) > 0  # 1 page * credits per page

    # Process with OCR
    create_response = await admin_client.post(
        "/v1/documents/document",
        json={
            "hash": upload_data.hash,
            "title": "OCR Test Image",
            "processor_slug": "mistral-ocr",
            "pages": None,  # Process all pages
        },
    )

    if create_response.status_code != 201:
        print(f"Create failed with status {create_response.status_code}")
        print(f"Response: {create_response.text}")
    assert create_response.status_code == 201
    doc_data = DocumentCreateResponse.model_validate(create_response.json())

    # Check that OCR extracted text
    blocks_response = await admin_client.get(f"/v1/documents/{doc_data.id}/blocks")
    assert blocks_response.status_code == 200
    blocks = [Block.model_validate(b) for b in blocks_response.json()]

    assert len(blocks) > 0
    # The test PDF contains "Test PDF Document"
    block_text = " ".join(block.text for block in blocks)
    assert "Test" in block_text or "PDF" in block_text or "Document" in block_text

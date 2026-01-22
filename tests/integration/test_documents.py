import pytest


@pytest.mark.asyncio
async def test_create_text_document_full_flow(subscribed_client):
    """Test creating and retrieving a text document."""
    response = await subscribed_client.post(
        "/v1/documents/text", json={"content": "This is an integration test document.", "title": "Integration Test"}
    )

    assert response.status_code == 201
    doc_data = response.json()

    # Retrieve the document
    doc_response = await subscribed_client.get(f"/v1/documents/{doc_data['id']}")
    assert doc_response.status_code == 200

    # Get blocks
    blocks_response = await subscribed_client.get(f"/v1/documents/{doc_data['id']}/blocks")
    assert blocks_response.status_code == 200
    blocks = blocks_response.json()
    assert len(blocks) == 1
    assert blocks[0]["text"] == "This is an integration test document."


@pytest.mark.asyncio
async def test_prepare_and_process_with_markitdown(subscribed_client):
    """Test document preparation and processing with markitdown (free processor)."""
    # Prepare from URL
    prepare_response = await subscribed_client.post(
        "/v1/documents/prepare",
        json={"url": "https://www.example.com"},  # Real URL
    )

    assert prepare_response.status_code == 200
    prepare_data = prepare_response.json()

    assert prepare_data["endpoint"] == "website"  # HTML content
    assert prepare_data["uncached_pages"] == []

    # Create document
    create_response = await subscribed_client.post(
        "/v1/documents/website", json={"hash": prepare_data["hash"], "title": "Example Website"}
    )

    assert create_response.status_code == 201

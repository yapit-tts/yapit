import uuid

import pytest


@pytest.mark.asyncio
async def test_create_document_and_paging(client):
    text = "Sentence one. Sentence two."

    r = await client.post(
        "/v1/documents/text",
        json={"content": text},
    )
    assert r.status_code == 201

    body = r.json()
    document_id = uuid.UUID(body["document_id"])  # validates UUID
    assert body["num_blocks"] == 1

    page = (await client.get(f"/v1/documents/{document_id}/blocks")).json()
    assert page["total"] == 1
    assert page["items"][0]["text"] == text

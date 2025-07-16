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
    document_id = uuid.UUID(body["id"])  # validates UUID

    blocks = (await client.get(f"/v1/documents/{document_id}/blocks")).json()
    assert len(blocks) == 1
    assert blocks[0]["text"] == text

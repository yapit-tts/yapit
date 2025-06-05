import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_create_document_and_paging(app: FastAPI):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        text = "Sentence one. Sentence two."

        r = await client.post(
            "/v1/documents",
            json={"source_type": "paste", "text_content": text},
        )
        assert r.status_code == 201

        body = r.json()
        document_id = uuid.UUID(body["document_id"])  # validates UUID
        assert body["num_blocks"] == 1

        page = (await client.get(f"/v1/documents/{document_id}/blocks")).json()
        assert page["total"] == 1
        assert page["items"][0]["text"] == text

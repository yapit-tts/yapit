import uuid

from fastapi import FastAPI

from fastapi.testclient import TestClient
import pytest


@pytest.mark.asyncio
async def test_create_document_and_paging(app: FastAPI):
    text = "Sentence one. Sentence two."

    print(f"Type of app: {type(app)}, should be FastAPI")

    client = TestClient(app=app)

    r = client.post(
        "/v1/documents",
        json={"source_type": "paste", "text_content": text},
        timeout=5,
    )
    assert r.status_code == 201

    body = r.json()
    document_id = uuid.UUID(body["document_id"])  # validates UUID
    assert body["num_blocks"] == 1

    page = client.get(f"/v1/documents/{document_id}/blocks").json()
    assert page["total"] == 1
    assert page["items"][0]["text"] == text

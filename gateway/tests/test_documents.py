import uuid

import requests

from .conftest import GATEWAY


def test_create_document_and_paging(wait_until_gateway):
    text = "Sentence one. Sentence two."

    r = requests.post(
        f"{GATEWAY}/v1/documents",
        json={"source_type": "paste", "text_content": text},
        timeout=5,
    )
    assert r.status_code == 201
    body = r.json()
    doc_id = uuid.UUID(body["document_id"])  # validates UUID
    assert body["num_blocks"] == 1

    page = requests.get(f"{GATEWAY}/v1/documents/{doc_id}/blocks").json()
    assert page["total"] == 1
    assert page["items"][0]["text"] == text

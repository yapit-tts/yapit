import uuid

import requests


def test_create_document_and_paging(wait_until_gateway, gateway_url: str):
    text = "Sentence one. Sentence two."

    r = requests.post(
        f"{gateway_url}/v1/documents",
        json={"source_type": "paste", "text_content": text},
        timeout=5,
    )
    assert r.status_code == 201
    body = r.json()
    document_id = uuid.UUID(body["document_id"])  # validates UUID
    assert body["num_blocks"] == 1

    page = requests.get(f"{gateway_url}/v1/documents/{document_id}/blocks").json()
    assert page["total"] == 1
    assert page["items"][0]["text"] == text

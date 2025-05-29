import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
import requests


# /filters/validate


@pytest.mark.asyncio
async def test_validate_regex_ok(app: FastAPI):
    client = TestClient(app=app)

    body = {
        "filter_config": {
            "regex_rules": [{"pattern": r"foo", "replacement": ""}],
        }
    }
    r = client.post(f"/v1/filters/validate", json=body, timeout=5)
    assert r.status_code == 200, r.json()
    assert r.json()["message"] == "ok"


@pytest.mark.asyncio
async def test_validate_regex_invalid(app: FastAPI):
    client = TestClient(app=app)

    body = {"filter_config": {"regex_rules": [{"pattern": "(", "replacement": ""}]}}
    r = client.post(f"/v1/filters/validate", json=body, timeout=5)
    assert r.status_code == 422, r.json()


# end-to-end filter flow


@pytest.mark.asyncio
async def test_apply_filters_and_blocks(app: FastAPI):
    client = TestClient(app=app)

    # 1. create document with URL + parentheses noise
    raw_text = "Hello (delete me) https://example.com world."
    doc = client.post(
        f"/v1/documents",
        json={"source_type": "paste", "text_content": raw_text},
        timeout=5,
    ).json()
    document_id = doc["document_id"]

    rules = [
        {"pattern": r"\bhttps?://\S+", "replacement": ""},
        {"pattern": r"\([^)]*\)", "replacement": ""},
    ]
    r = client.post(
        f"/v1/documents/{document_id}/apply_filters",
        json={"filter_config": {"regex_rules": rules}},
        timeout=5,
    )
    assert r.status_code == 202, r.json()

    # 4. wait for completion
    _poll_status(client, document_id, "done")

    # 5. verify blocks were rewritten and garbage removed
    blocks = client.get(f"/v1/documents/{document_id}/blocks").json()["items"]
    assert blocks  # still at least one block
    clean_text = " ".join(b["text"] for b in blocks)
    assert "http" not in clean_text and "(" not in clean_text


def _poll_status(client: TestClient, document_id: str, expect: str, timeout: float = 15.0) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        msg = client.get(f"/v1/documents/{document_id}/filter_status").json()["message"]
        if msg == expect or msg.startswith(expect):  # done | cancelled | error:...
            return
        time.sleep(0.25)
    raise RuntimeError(f"filter_status never reached {expect!r} (last={msg!r})")

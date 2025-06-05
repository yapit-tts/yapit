import time

import pytest
import requests
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# /filters/validate


@pytest.mark.asyncio
async def test_validate_regex_ok(app: FastAPI):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        body = {
            "filter_config": {
                "regex_rules": [{"pattern": r"foo", "replacement": ""}],
            }
        }
        r = await client.post(f"/v1/filters/validate", json=body)
        assert r.status_code == 200, r.json()
        assert r.json()["message"] == "ok"


@pytest.mark.asyncio
async def test_validate_regex_invalid(app: FastAPI):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        body = {"filter_config": {"regex_rules": [{"pattern": "(", "replacement": ""}]}}
        r = await client.post(f"/v1/filters/validate", json=body)
        assert r.status_code == 422, r.json()


# end-to-end filter flow


@pytest.mark.asyncio
async def test_apply_filters_and_blocks(app: FastAPI):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. create document with URL + parentheses noise
        raw_text = "Hello (delete me) https://example.com world."
        doc = (
            await client.post(
                f"/v1/documents",
                json={"source_type": "paste", "text_content": raw_text},
            )
        ).json()
        document_id = doc["document_id"]

        rules = [
            {"pattern": r"\bhttps?://\S+", "replacement": ""},
            {"pattern": r"\([^)]*\)", "replacement": ""},
        ]
        r = await client.post(
            f"/v1/documents/{document_id}/apply_filters",
            json={"filter_config": {"regex_rules": rules}},
        )
        assert r.status_code == 202, r.json()

        # 4. wait for completion
        await _poll_status(client, document_id, "done")

        # 5. verify blocks were rewritten and garbage removed
        blocks = (await client.get(f"/v1/documents/{document_id}/blocks")).json()["items"]
        assert blocks  # still at least one block
        clean_text = " ".join(b["text"] for b in blocks)
        assert "http" not in clean_text and "(" not in clean_text


async def _poll_status(client: AsyncClient, document_id: str, expect: str, timeout: float = 15.0) -> None:
    import asyncio

    t0 = time.time()
    while time.time() - t0 < timeout:
        msg = (await client.get(f"/v1/documents/{document_id}/filter_status")).json()["message"]
        if msg == expect or msg.startswith(expect):  # done | cancelled | error:...
            return
        await asyncio.sleep(0.25)
    raise RuntimeError(f"filter_status never reached {expect!r} (last={msg!r})")

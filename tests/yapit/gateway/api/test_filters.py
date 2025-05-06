import time

import requests


def _poll_status(gateway_url: str, document_id: str, expect: str, timeout: float = 15.0) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        msg = requests.get(f"{gateway_url}/v1/documents/{document_id}/filter_status").json()["message"]
        if msg == expect or msg.startswith(expect):  # done | cancelled | error:...
            return
        time.sleep(0.25)
    raise RuntimeError(f"filter_status never reached {expect!r} (last={msg!r})")


# /filters/validate


def test_validate_regex_ok(wait_until_gateway, gateway_url: str):
    body = {"filter_config": {"regex_rules": [{"pattern": r"foo", "replacement": ""}]}}
    r = requests.post(f"{gateway_url}/v1/filters/validate", json=body, timeout=5)
    assert r.status_code == 200, r.json()
    assert r.json()["message"] == "ok"


def test_validate_regex_invalid(wait_until_gateway, gateway_url: str):
    body = {"filter_config": {"regex_rules": [{"pattern": "(", "replacement": ""}]}}
    r = requests.post(f"{gateway_url}/v1/filters/validate", json=body, timeout=5)
    assert r.status_code == 422, r.json()


# end-to-end filter flow


def test_apply_filters_and_blocks(wait_until_gateway, gateway_url: str):
    # 1. create document with URL + parentheses noise
    raw_text = "Hello (delete me) https://example.com world."
    doc = requests.post(
        f"{gateway_url}/v1/documents",
        json={"source_type": "paste", "text_content": raw_text},
        timeout=5,
    ).json()
    document_id = doc["document_id"]

    rules = [
        {"pattern": r"\bhttps?://\S+", "replacement": ""},
        {"pattern": r"\([^)]*\)", "replacement": ""},
    ]
    r = requests.post(
        f"{gateway_url}/v1/documents/{document_id}/apply_filters",
        json={"filter_config": {"regex_rules": rules}},
        timeout=5,
    )
    assert r.status_code == 202, r.json()

    # 4. wait for completion
    _poll_status(gateway_url, document_id, "done")

    # 5. verify blocks were rewritten and garbage removed
    blocks = requests.get(f"{gateway_url}/v1/documents/{document_id}/blocks").json()["items"]
    assert blocks  # still at least one block
    clean_text = " ".join(b["text"] for b in blocks)
    assert "http" not in clean_text and "(" not in clean_text

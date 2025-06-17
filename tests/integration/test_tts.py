"""End-to-end integration test for TTS generation."""

import os

import httpx
import pytest
import requests


def get_dev_token():
    """Get access token for dev user."""
    api_host = os.getenv("DEV_STACK_AUTH_API_HOST", "http://localhost:8102")
    project_id = os.getenv("STACK_AUTH_PROJECT_ID")
    client_key = os.getenv("STACK_AUTH_CLIENT_KEY")

    if not project_id or not client_key:
        raise RuntimeError("Missing STACK_AUTH_PROJECT_ID or STACK_AUTH_CLIENT_KEY")

    # Sign in as dev user
    headers = {
        "X-Stack-Access-Type": "client",
        "X-Stack-Project-Id": project_id,
        "X-Stack-Publishable-Client-Key": client_key,
    }

    r = requests.post(
        f"{api_host}/api/v1/auth/password/sign-in",
        headers=headers,
        json={"email": "dev@example.com", "password": "dev-password-123"},
    )

    if r.status_code not in [200, 201]:
        raise RuntimeError(f"Failed to sign in: {r.status_code} {r.text}")

    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_tts_integration():
    """Test complete TTS flow from document creation to audio retrieval.

    Requires: gateway, postgres, redis, and kokoro worker running.
    """
    # Get auth token
    token = get_dev_token()
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=70.0, headers=headers) as client:
        # Step 1: Create document
        doc_response = await client.post(
            "/v1/documents", json={"source_type": "paste", "text_content": "Hello integration test!"}
        )
        assert doc_response.status_code == 201
        doc_data = doc_response.json()
        document_id = doc_data["document_id"]
        block_id = doc_data["blocks"][0]["id"]

        # Step 2: Request synthesis with long-polling
        # This should block until audio is ready (or timeout)
        import time

        start_time = time.time()

        synth_response = await client.post(
            f"/v1/documents/{document_id}/blocks/{block_id}/synthesize",
            json={"model_slug": "kokoro-cpu", "voice_slug": "af_heart", "speed": 1.0},
        )

        elapsed = time.time() - start_time
        print(f"Synthesis took {elapsed:.2f} seconds")

        # Should get audio directly
        assert synth_response.status_code == 200
        assert "audio/" in synth_response.headers["content-type"]
        assert "X-Audio-Codec" in synth_response.headers
        assert "X-Sample-Rate" in synth_response.headers
        assert "X-Channels" in synth_response.headers
        assert "X-Sample-Width" in synth_response.headers
        assert "X-Duration-Ms" in synth_response.headers
        assert len(synth_response.content) > 0
        assert any(b != 0 for b in synth_response.content)

        # Step 3: Request same synthesis again - should return immediately from cache
        start_time = time.time()

        cached_response = await client.post(
            f"/v1/documents/{document_id}/blocks/{block_id}/synthesize",
            json={"model_slug": "kokoro-cpu", "voice_slug": "af_heart", "speed": 1.0},
        )

        elapsed = time.time() - start_time
        print(f"Cached synthesis took {elapsed:.2f} seconds")
        assert cached_response.status_code == 200
        assert cached_response.content == synth_response.content
        assert cached_response.headers["X-Audio-Codec"] == synth_response.headers["X-Audio-Codec"]

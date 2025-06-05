"""End-to-end integration test for TTS generation."""

import asyncio
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

    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=30.0, headers=headers) as client:
        # Step 1: Create document
        doc_response = await client.post(
            "/v1/documents", json={"source_type": "paste", "text_content": "Hello integration test!"}
        )
        assert doc_response.status_code == 201
        doc_data = doc_response.json()
        document_id = doc_data["document_id"]
        block_id = doc_data["blocks"][0]["id"]

        # Step 2: Request synthesis
        synth_response = await client.post(
            f"/v1/documents/{document_id}/blocks/{block_id}/synthesize",
            json={"model_slug": "kokoro", "voice_slug": "af_heart", "speed": 1.0},
        )
        assert synth_response.status_code == 201
        synth_data = synth_response.json()
        audio_url = synth_data["audio_url"]

        # Step 3: Get audio - should initially return 202 while processing
        audio_response = await client.get(audio_url)

        # Verify we get 202 initially (unless synthesis was super fast)
        if audio_response.status_code == 202:
            print("Got expected 202 - synthesis in progress")

            # Poll until we get the audio
            for attempt in range(15):  # Max 15 seconds
                await asyncio.sleep(1)
                audio_response = await client.get(audio_url)

                if audio_response.status_code == 200:
                    print(f"Got 200 after {attempt + 1} seconds")
                    break
                elif audio_response.status_code == 202:
                    continue  # Still processing
                else:
                    # Unexpected status
                    print(f"Unexpected status: {audio_response.status_code}")
                    assert False, f"Unexpected status code: {audio_response.status_code}"

        # Should get actual audio data
        assert audio_response.status_code == 200
        assert audio_response.headers["content-type"] == "audio/pcm"
        assert len(audio_response.content) > 0
        assert any(b != 0 for b in audio_response.content)

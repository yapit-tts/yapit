"""Integration tests for browser TTS audio submission endpoint."""

import base64

import pytest


@pytest.mark.asyncio
async def test_submit_audio_and_retrieve(regular_client, unique_document):
    """Test that browser-synthesized audio can be submitted and retrieved."""
    document_id = unique_document["id"]
    block_idx = unique_document["blocks"][0]["idx"]

    fake_audio = b"\x00\x01\x02\x03" * 250  # 1KB
    audio_b64 = base64.b64encode(fake_audio).decode()

    response = await regular_client.post(
        "/v1/audio",
        json={
            "document_id": document_id,
            "block_idx": block_idx,
            "model": "kokoro",
            "voice": "af_heart",
            "audio": audio_b64,
            "duration_ms": 500,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "variant_hash" in data
    assert "audio_url" in data
    assert data["audio_url"].startswith("/v1/audio/")

    # Retrieve and verify - backend wraps PCM in WAV header with silence padding
    audio_response = await regular_client.get(data["audio_url"])
    assert audio_response.status_code == 200
    wav_data = audio_response.content
    assert wav_data[:4] == b"RIFF"
    assert wav_data[8:12] == b"WAVE"
    # WAV header is 44 bytes, audio data follows (with silence padding appended)
    assert wav_data[44 : 44 + len(fake_audio)] == fake_audio


@pytest.mark.asyncio
async def test_submit_audio_too_large(regular_client, regular_document):
    """Test that oversized audio is rejected."""
    document_id = regular_document["id"]
    block_idx = regular_document["blocks"][0]["idx"]

    # 11MB exceeds 10MB limit
    huge_audio = b"\x00" * (11 * 1024 * 1024)
    audio_b64 = base64.b64encode(huge_audio).decode()

    response = await regular_client.post(
        "/v1/audio",
        json={
            "document_id": document_id,
            "block_idx": block_idx,
            "model": "kokoro",
            "voice": "af_heart",
            "audio": audio_b64,
            "duration_ms": 500,
        },
    )
    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_submit_audio_wrong_document(regular_client, test_document):
    """Test that users can't submit audio to other users' documents."""
    # test_document belongs to admin, regular_client is a different user
    document_id = test_document["id"]
    block_idx = test_document["blocks"][0]["idx"]

    fake_audio = b"\x00" * 100
    audio_b64 = base64.b64encode(fake_audio).decode()

    response = await regular_client.post(
        "/v1/audio",
        json={
            "document_id": document_id,
            "block_idx": block_idx,
            "model": "kokoro",
            "voice": "af_heart",
            "audio": audio_b64,
            "duration_ms": 100,
        },
    )
    assert response.status_code == 403

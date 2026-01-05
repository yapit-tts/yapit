import time

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model_slug,voice_slug",
    [
        ("kokoro", "af_heart"),
        pytest.param("higgs", "en-man", marks=pytest.mark.runpod),
        pytest.param("inworld", "ashley", marks=pytest.mark.inworld),
    ],
)
async def test_tts_integration(model_slug, voice_slug, admin_ws_client, admin_client, test_document):
    """Test complete TTS flow via WebSocket from document creation to audio retrieval."""
    document_id = test_document["id"]
    block_idx = test_document["blocks"][0]["idx"]

    # Request synthesis via WebSocket
    start_time = time.time()

    await admin_ws_client.synthesize(
        document_id=document_id,
        block_indices=[block_idx],
        model=model_slug,
        voice=voice_slug,
        synthesis_mode="server",
    )

    # Wait for "queued" or "cached" status
    status_msg = await admin_ws_client.wait_for_any_status(block_idx, timeout=10.0)
    assert status_msg is not None, "No status message received"
    assert status_msg["status"] in ("queued", "cached")

    # If queued, wait for "cached" status (synthesis completion)
    if status_msg["status"] == "queued":
        cached_msg = await admin_ws_client.wait_for_status(block_idx, "cached", timeout=120.0)
        assert cached_msg is not None, "Synthesis timed out waiting for cached status"
        audio_url = cached_msg["audio_url"]
    else:
        audio_url = status_msg["audio_url"]

    elapsed = time.time() - start_time
    print(f"Synthesis took {elapsed:.2f} seconds")

    # Fetch audio via HTTP GET
    audio_response = await admin_client.get(audio_url)
    assert audio_response.status_code == 200
    assert "audio/" in audio_response.headers["content-type"]
    assert len(audio_response.content) > 0
    assert any(b != 0 for b in audio_response.content)

    # Request same block again - should return cached immediately
    admin_ws_client.messages.clear()
    start_time = time.time()

    await admin_ws_client.synthesize(
        document_id=document_id,
        block_indices=[block_idx],
        model=model_slug,
        voice=voice_slug,
        synthesis_mode="server",
    )

    cached_status = await admin_ws_client.wait_for_status(block_idx, "cached", timeout=5.0)
    elapsed = time.time() - start_time
    print(f"Cached synthesis took {elapsed:.2f} seconds")

    assert cached_status is not None
    assert cached_status["audio_url"] == audio_url

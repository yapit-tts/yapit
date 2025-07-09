import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model_slug",
    [
        "kokoro-cpu",
        pytest.param("kokoro-cpu-runpod", marks=pytest.mark.runpod),
    ],
)
async def test_tts_integration(model_slug, admin_client, test_document):
    """Test complete TTS flow from document creation to audio retrieval."""
    document_id = test_document["document_id"]
    block_id = test_document["blocks"][0]["id"]

    # Step 2: Request synthesis with long-polling
    # This should block until audio is ready (or timeout)
    import time

    start_time = time.time()

    synth_response = await admin_client.post(
        f"/v1/documents/{document_id}/blocks/{block_id}/synthesize",
        json={"model_slug": model_slug, "voice_slug": "af_heart", "speed": 1.0},
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

    cached_response = await admin_client.post(
        f"/v1/documents/{document_id}/blocks/{block_id}/synthesize",
        json={"model_slug": model_slug, "voice_slug": "af_heart", "speed": 1.0},
    )

    elapsed = time.time() - start_time
    print(f"Cached synthesis took {elapsed:.2f} seconds")
    assert cached_response.status_code == 200
    assert cached_response.content == synth_response.content
    assert cached_response.headers["X-Audio-Codec"] == synth_response.headers["X-Audio-Codec"]

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from yapit.contracts.redis_keys import TTS_INFLIGHT
from yapit.gateway.cache import Cache
from yapit.gateway.deps import get_audio_cache


@pytest.mark.asyncio
async def test_get_audio_returns_synthesized_data(app: FastAPI, redis_client):
    """Test that we can fetch synthesized audio data via HTTP."""
    # Mock the cache to return our test audio
    test_audio = b"PCM_AUDIO_DATA_HERE"
    mock_cache = AsyncMock(spec=Cache)
    mock_cache.retrieve_data.return_value = None  # First call returns None (not cached yet)
    mock_cache.exists.return_value = False  # Not cached
    app.dependency_overrides[get_audio_cache] = lambda: mock_cache
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Create document and synthesize
        r = await client.post("/v1/documents", json={"source_type": "paste", "text_content": "Test audio."})
        doc = r.json()
        document_id = doc["document_id"]
        block_id = doc["blocks"][0]["id"]

        r = await client.post(
            f"/v1/documents/{document_id}/blocks/{block_id}/synthesize",
            json={"model_slug": "kokoro", "voice_slug": "af_heart", "speed": 1.0},
        )
        assert r.status_code == 201
        synth = r.json()
        variant_hash = synth["variant_hash"]

        # Verify we get audio_url instead of ws_url
        assert "audio_url" in synth
        assert synth["audio_url"] == f"/v1/documents/{document_id}/blocks/{block_id}/variants/{variant_hash}/audio"

        # Test 202 response while synthesis is in progress
        r = await client.get(synth["audio_url"])
        assert r.status_code == 202  # Still processing

        # Simulate completion: remove inflight flag and make cache return the audio
        await redis_client.delete(TTS_INFLIGHT.format(hash=variant_hash))
        mock_cache.retrieve_data.return_value = test_audio

        # Now fetch audio via HTTP - should get 200 from cache
        r = await client.get(synth["audio_url"])
        assert r.status_code == 200
        assert r.content == test_audio
        assert r.headers["content-type"] in ["audio/pcm", "audio/wav"]  # Accept either for now

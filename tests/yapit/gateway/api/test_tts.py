import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from yapit.contracts.redis_keys import TTS_INFLIGHT
from yapit.gateway.cache import Cache
from yapit.gateway.deps import get_audio_cache


@pytest.mark.asyncio
async def test_synthesize_returns_cached_audio_immediately(app: FastAPI):
    """Test that synthesize returns cached audio immediately without queueing."""
    test_audio = b"CACHED_PCM_AUDIO_DATA"
    mock_cache = AsyncMock(spec=Cache)
    mock_cache.retrieve_data.return_value = test_audio
    mock_cache.exists.return_value = True
    app.dependency_overrides[get_audio_cache] = lambda: mock_cache

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=70.0) as client:
        # Create document
        r = await client.post("/v1/documents", json={"source_type": "paste", "text_content": "Test cached audio."})
        doc = r.json()
        document_id = doc["document_id"]
        block_id = doc["blocks"][0]["id"]

        # Synthesize - should return audio immediately from cache
        r = await client.post(
            f"/v1/documents/{document_id}/blocks/{block_id}/synthesize",
            json={"model_slug": "kokoro-cpu", "voice_slug": "af_heart", "speed": 1.0},
        )
        assert r.status_code == 200
        assert r.content == test_audio
        assert "audio/" in r.headers["content-type"]
        assert "X-Audio-Codec" in r.headers
        assert "X-Sample-Rate" in r.headers
        assert "X-Channels" in r.headers
        assert "X-Sample-Width" in r.headers
        assert "X-Duration-Ms" in r.headers

from unittest.mock import AsyncMock

import pytest

from yapit.gateway.cache import Cache
from yapit.gateway.deps import get_audio_cache


@pytest.mark.asyncio
async def test_synthesize_returns_cached_audio_immediately(client, app, as_admin_user):
    """Test that synthesize returns cached audio immediately without queueing."""
    test_audio = b"CACHED_PCM_AUDIO_DATA"
    mock_cache = AsyncMock(spec=Cache)
    mock_cache.retrieve_data.return_value = test_audio
    mock_cache.exists.return_value = True
    app.dependency_overrides[get_audio_cache] = lambda: mock_cache

    # Create document
    r = await client.post("/v1/documents/text", json={"content": "Test cached audio."})
    doc = r.json()
    document_id = doc["id"]

    # Fetch blocks
    blocks_response = await client.get(f"/v1/documents/{document_id}/blocks")
    block_id = blocks_response.json()[0]["id"]

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

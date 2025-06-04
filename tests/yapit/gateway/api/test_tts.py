import asyncio
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
import pytest
from yapit.contracts.redis_keys import TTS_AUDIO, TTS_INFLIGHT


@pytest.mark.asyncio
async def test_get_audio_returns_synthesized_data(app: FastAPI, redis_client):
    """Test that we can fetch synthesized audio data via HTTP."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Create document and synthesize
        r = await client.post(
            "/v1/documents",
            json={"source_type": "paste", "text_content": "Test audio."}
        )
        doc = r.json()
        document_id = doc["document_id"]
        block_id = doc["blocks"][0]["id"]
        
        r = await client.post(
            f"/v1/documents/{document_id}/blocks/{block_id}/synthesize",
            json={"model_slug": "kokoro", "voice_slug": "af_heart", "speed": 1.0}
        )
        assert r.status_code == 201
        variant_hash = r.json()["variant_hash"]
        
        # Simulate worker putting audio in Redis
        test_audio = b"PCM_AUDIO_DATA_HERE"
        await redis_client.set(TTS_AUDIO.format(hash=variant_hash), test_audio, ex=3600)
        
        # Fetch audio via HTTP
        r = await client.get(
            f"/v1/documents/{document_id}/blocks/{block_id}/variants/{variant_hash}/audio"
        )
        assert r.status_code == 200
        assert r.content == test_audio
        assert r.headers["content-type"] in ["audio/pcm", "audio/wav"]  # Accept either for now


@pytest.mark.asyncio
async def test_get_audio_waits_for_worker_completion(app: FastAPI, redis_client):
    """Test that HTTP endpoint waits for synthesis to complete before returning."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Create document and synthesize
        r = await client.post(
            "/v1/documents",
            json={"source_type": "paste", "text_content": "Async test."}
        )
        doc = r.json()
        document_id = doc["document_id"]
        block_id = doc["blocks"][0]["id"]
        
        r = await client.post(
            f"/v1/documents/{document_id}/blocks/{block_id}/synthesize",
            json={"model_slug": "kokoro", "voice_slug": "af_heart", "speed": 1.0}
        )
        variant_hash = r.json()["variant_hash"]
        
        # Mark synthesis as in-progress
        await redis_client.set(TTS_INFLIGHT.format(hash=variant_hash), "1", ex=300)
        
        # Simulate worker completing after delay
        async def simulate_worker():
            await asyncio.sleep(0.5)
            test_audio = b"DELAYED_AUDIO_DATA"
            await redis_client.delete(TTS_INFLIGHT.format(hash=variant_hash))
            await redis_client.set(TTS_AUDIO.format(hash=variant_hash), test_audio, ex=3600)
        
        worker_task = asyncio.create_task(simulate_worker())
        
        # Request should wait and return the audio
        r = await client.get(
            f"/v1/documents/{document_id}/blocks/{block_id}/variants/{variant_hash}/audio",
            timeout=2.0
        )
        
        await worker_task
        
        assert r.status_code == 200
        assert r.content == b"DELAYED_AUDIO_DATA"
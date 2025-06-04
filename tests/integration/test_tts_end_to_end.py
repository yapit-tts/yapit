"""End-to-end integration test for TTS generation."""

import asyncio
import os
import pytest
import httpx


@pytest.mark.asyncio
async def test_tts_generation_end_to_end():
    """Test complete TTS flow from document creation to audio retrieval.
    
    Requires: gateway, postgres, redis, and kokoro worker running.
    """
    # Use test token if available, otherwise no auth
    headers = {}
    test_token = os.getenv("TEST_AUTH_TOKEN")
    if test_token:
        headers["Authorization"] = f"Bearer {test_token}"
    
    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=30.0, headers=headers) as client:
        
        # Step 1: Create document
        doc_response = await client.post(
            "/v1/documents",
            json={
                "source_type": "paste",
                "text_content": "Hello integration test!"
            }
        )
        assert doc_response.status_code == 201
        doc_data = doc_response.json()
        document_id = doc_data["document_id"]
        block_id = doc_data["blocks"][0]["id"]
        
        # Step 2: Request synthesis
        synth_response = await client.post(
            f"/v1/documents/{document_id}/blocks/{block_id}/synthesize",
            json={
                "model_slug": "kokoro",
                "voice_slug": "af_heart",
                "speed": 1.0
            }
        )
        assert synth_response.status_code == 201
        synth_data = synth_response.json()
        variant_hash = synth_data["variant_hash"]
        audio_url = synth_data["audio_url"]
        
        # Step 3: Get audio - retry a few times as synthesis takes time
        audio_response = None
        for attempt in range(10):
            audio_response = await client.get(audio_url)
            if audio_response.status_code == 200:
                break
            await asyncio.sleep(1)
        
        # Should get actual audio data
        assert audio_response.status_code == 200
        assert audio_response.headers["content-type"] == "audio/pcm"
        assert len(audio_response.content) > 0
        
        # Verify it's valid PCM data (not empty/all zeros)
        assert any(b != 0 for b in audio_response.content)
import asyncio
import uuid

import pytest


@pytest.mark.asyncio
async def test_client_processor_flow(admin_client, test_document):
    """Test complete client processor flow from synthesis request to result submission."""
    document_id = test_document["id"]
    block_id = test_document["blocks"][0]["id"]

    # Generate job_id client-side
    job_id = str(uuid.uuid4())

    # Fake audio result
    fake_audio = b"FAKE_CLIENT_AUDIO"
    duration_ms = 1500

    async def request_synthesis():
        """Request synthesis with client-provided job_id - will block until result is submitted."""
        response = await admin_client.post(
            f"/v1/documents/{document_id}/blocks/{block_id}/synthesize/models/kokoro-client-free/voices/af_heart"
            f"?job_id={job_id}",
        )
        return response

    async def submit_result():
        """Submit the synthesis result after a short delay to ensure job is queued."""
        await asyncio.sleep(2)  # Wait longer for job to be queued and picked up by processor

        response = await admin_client.post(
            f"/v1/tts/submit/model/kokoro-client-free/job/{job_id}",
            json={
                "job_id": job_id,
                "audio": fake_audio.decode("latin-1"),  # Convert bytes to string for JSON
                "duration_ms": duration_ms,
            },
        )
        if response.status_code != 200:
            print(f"Submit failed with status {response.status_code}: {response.text}")
        return response

    # Run synthesis request and result submission concurrently
    synth_task = asyncio.create_task(request_synthesis())
    submit_task = asyncio.create_task(submit_result())

    synth_response = await synth_task
    submit_response = await submit_task

    # Verify synthesis completed successfully
    assert synth_response.status_code == 200
    assert submit_response.status_code == 200

    # Verify audio headers are present
    assert "X-Audio-Codec" in synth_response.headers
    assert "X-Duration-Ms" in synth_response.headers
    assert int(synth_response.headers["X-Duration-Ms"]) == duration_ms

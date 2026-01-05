"""Integration tests for TTS with subscription/usage limits via WebSocket.

NOTE: Cache hits not recording usage is verified by code inspection (ws.py returns
early for cache hits before queueing jobs, so record_usage in the TTS processor
never runs). If that code path changes significantly, consider adding a proper test
with a subscribed user that checks UsagePeriod counters before/after cache hits.
"""

import asyncio

import pytest


@pytest.mark.asyncio
async def test_tts_usage_limit_exceeded(regular_ws_client, regular_document):
    """Test that TTS fails via WS when user has no subscription (free tier)."""
    document_id = regular_document["id"]
    block_idx = regular_document["blocks"][0]["idx"]

    await regular_ws_client.synthesize(
        document_id=document_id,
        block_indices=[block_idx],
        model="kokoro",
        voice="af_heart",
        synthesis_mode="server",
    )

    await asyncio.sleep(0.5)  # Wait for message

    error_msgs = [m for m in regular_ws_client.messages if m.get("type") == "error"]
    assert len(error_msgs) > 0
    assert "usage limit exceeded" in error_msgs[0]["error"].lower()


@pytest.mark.asyncio
async def test_tts_cached_no_additional_synthesis(admin_ws_client, admin_client, test_document):
    """Test that cached audio returns immediately without re-synthesis.

    This verifies cache hits don't trigger the TTS processor (and thus don't
    record additional usage). The second request should return 'cached' status
    immediately rather than 'queued'.
    """
    document_id = test_document["id"]
    block_idx = test_document["blocks"][0]["idx"]

    # First synthesis
    await admin_ws_client.synthesize(
        document_id=document_id,
        block_indices=[block_idx],
        model="kokoro",
        voice="af_heart",
        synthesis_mode="server",
    )

    # Wait for completion
    cached_msg = await admin_ws_client.wait_for_status(block_idx, "cached", timeout=120.0)
    assert cached_msg is not None
    first_audio_url = cached_msg["audio_url"]

    # Clear messages and request same block again
    admin_ws_client.messages.clear()

    await admin_ws_client.synthesize(
        document_id=document_id,
        block_indices=[block_idx],
        model="kokoro",
        voice="af_heart",
        synthesis_mode="server",
    )

    # Second request should get 'cached' status immediately (not 'queued')
    # because it's a cache hit — no actual synthesis happens
    status_msg = await admin_ws_client.wait_for_any_status(block_idx, timeout=5.0)
    assert status_msg is not None
    assert status_msg["status"] == "cached", "Second request should be cache hit"
    assert status_msg["audio_url"] == first_audio_url

    # Verify audio is valid
    audio_response = await admin_client.get(first_audio_url)
    assert audio_response.status_code == 200
    assert len(audio_response.content) > 0


@pytest.mark.asyncio
async def test_tts_admin_no_usage_limit(admin_ws_client, admin_client, test_document):
    """Test that admins bypass subscription limits via WS."""
    document_id = test_document["id"]
    block_idx = test_document["blocks"][0]["idx"]

    await admin_ws_client.synthesize(
        document_id=document_id,
        block_indices=[block_idx],
        model="kokoro",
        voice="af_heart",
        synthesis_mode="server",
    )

    # Should get queued or cached status (not error)
    status_msg = await admin_ws_client.wait_for_any_status(block_idx, timeout=10.0)
    assert status_msg is not None
    assert status_msg["status"] in ("queued", "cached")

    # Wait for completion if queued
    if status_msg["status"] == "queued":
        cached_msg = await admin_ws_client.wait_for_status(block_idx, "cached", timeout=120.0)
        assert cached_msg is not None
        audio_url = cached_msg["audio_url"]
    else:
        audio_url = status_msg["audio_url"]

    # Fetch audio to verify
    audio_response = await admin_client.get(audio_url)
    assert audio_response.status_code == 200
    assert len(audio_response.content) > 0

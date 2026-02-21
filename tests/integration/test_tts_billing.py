"""Integration tests for TTS with subscription/usage limits via WebSocket.

NOTE: Cache hits not recording usage is verified by code inspection (ws.py returns
early for cache hits before queueing jobs, so record_usage in the TTS processor
never runs). If that code path changes significantly, consider adding a proper test
with a subscribed user that checks UsagePeriod counters before/after cache hits.
"""

import asyncio

import pytest

from tests.integration.conftest import (
    create_unique_user,
    get_auth_token,
    make_client,
    make_ws_client,
    provision_subscription,
)


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
    )

    await asyncio.sleep(0.5)  # Wait for message

    error_msgs = [m for m in regular_ws_client.messages if m.get("status") == "error"]
    assert len(error_msgs) > 0, "If you set BILLING_ENABLED=false for dev, this test is expected to fail."
    assert "usage limit exceeded" in error_msgs[0]["error"].lower()


@pytest.mark.asyncio
async def test_tts_cached_no_additional_synthesis(subscribed_ws_client, subscribed_client, test_document):
    """Test that cached audio returns immediately without re-synthesis.

    This verifies cache hits don't trigger the TTS processor (and thus don't
    record additional usage). The second request should return 'cached' status
    immediately rather than 'queued'.
    """
    document_id = test_document["id"]
    block_idx = test_document["blocks"][0]["idx"]

    # First synthesis
    await subscribed_ws_client.synthesize(
        document_id=document_id,
        block_indices=[block_idx],
        model="kokoro",
        voice="af_heart",
    )

    # Wait for completion
    cached_msg = await subscribed_ws_client.wait_for_status(block_idx, "cached", timeout=120.0)
    assert cached_msg is not None
    first_audio_url = cached_msg["audio_url"]

    # Clear messages and request same block again
    subscribed_ws_client.messages.clear()

    await subscribed_ws_client.synthesize(
        document_id=document_id,
        block_indices=[block_idx],
        model="kokoro",
        voice="af_heart",
    )

    # Second request should get 'cached' status immediately (not 'queued')
    # because it's a cache hit — no actual synthesis happens
    status_msg = await subscribed_ws_client.wait_for_any_status(block_idx, timeout=5.0)
    assert status_msg is not None
    assert status_msg["status"] == "cached", "Second request should be cache hit"
    assert status_msg["audio_url"] == first_audio_url

    # Verify audio is valid
    audio_response = await subscribed_client.get(first_audio_url)
    assert audio_response.status_code == 200
    assert len(audio_response.content) > 0


@pytest.mark.asyncio
async def test_cross_user_audio_sharing():
    """Test that User B can access cached audio from User A's identical text.

    This verifies the BlockVariant schema fix: audio is content-addressed and
    shared across users. User B should get a cache hit and be able to fetch
    audio that User A synthesized.
    """
    shared_text = "This exact text will be synthesized by user A and cached for user B."

    # Create two separate subscribed users
    user_a_data = create_unique_user()
    user_a_data["token"] = get_auth_token(user_a_data["email"], user_a_data["password"])
    await provision_subscription(user_a_data["id"])

    user_b_data = create_unique_user()
    user_b_data["token"] = get_auth_token(user_b_data["email"], user_b_data["password"])
    await provision_subscription(user_b_data["id"])

    # User A: create document and synthesize
    async for client_a in make_client(user_a_data["token"]):
        doc_a_response = await client_a.post("/v1/documents/text", json={"content": shared_text})
        assert doc_a_response.status_code == 201
        doc_a = doc_a_response.json()

        blocks_a = (await client_a.get(f"/v1/documents/{doc_a['id']}/blocks")).json()

        ws_a = await make_ws_client(user_a_data["token"])
        try:
            await ws_a.synthesize(
                document_id=doc_a["id"],
                block_indices=[blocks_a[0]["idx"]],
                model="kokoro",
                voice="af_heart",
            )

            # Wait for synthesis to complete
            cached_msg = await ws_a.wait_for_status(blocks_a[0]["idx"], "cached", timeout=120.0)
            assert cached_msg is not None
            audio_url_a = cached_msg["audio_url"]

            # Verify User A can fetch
            audio_a = await client_a.get(audio_url_a)
            assert audio_a.status_code == 200
            audio_content = audio_a.content
        finally:
            await ws_a.close()

    # User B: create document with SAME text and request synthesis
    async for client_b in make_client(user_b_data["token"]):
        doc_b_response = await client_b.post("/v1/documents/text", json={"content": shared_text})
        assert doc_b_response.status_code == 201
        doc_b = doc_b_response.json()

        blocks_b = (await client_b.get(f"/v1/documents/{doc_b['id']}/blocks")).json()

        ws_b = await make_ws_client(user_b_data["token"])
        try:
            await ws_b.synthesize(
                document_id=doc_b["id"],
                block_indices=[blocks_b[0]["idx"]],
                model="kokoro",
                voice="af_heart",
            )

            # User B should get immediate cache hit (not "queued")
            status_msg = await ws_b.wait_for_any_status(blocks_b[0]["idx"], timeout=5.0)
            assert status_msg is not None
            assert status_msg["status"] == "cached", "User B should get cache hit from User A's synthesis"

            audio_url_b = status_msg["audio_url"]

            # URLs should be identical (same content hash)
            assert audio_url_b == audio_url_a

            # User B should be able to fetch the audio
            audio_b = await client_b.get(audio_url_b)
            assert audio_b.status_code == 200, "User B should be able to fetch audio from shared cache"
            assert audio_b.content == audio_content
        finally:
            await ws_b.close()

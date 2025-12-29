"""Integration tests for TTS with billing/credits via WebSocket."""

from decimal import Decimal

import pytest

from tests.integration.conftest import make_ws_client


async def grant_credits_via_api(admin_client, user_id: str, amount: Decimal):
    """Grant credits to a user using the admin API."""
    response = await admin_client.post(
        f"/v1/admin/users/{user_id}/credits",
        json={
            "amount": str(amount),
            "description": "Test credit grant",
            "type": "credit_bonus",
        },
    )
    assert response.status_code == 200
    return response.json()


async def get_user_credits_via_api(user_client) -> dict:
    """Get user credits using the user API."""
    response = await user_client.get("/v1/users/me/credits")
    if response.status_code == 404:
        return {"balance": "0"}
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_tts_insufficient_credits(regular_ws_client, regular_document):
    """Test that TTS fails via WS when user has no credits."""
    document_id = regular_document["id"]
    block_idx = regular_document["blocks"][0]["idx"]

    await regular_ws_client.synthesize(
        document_id=document_id,
        block_indices=[block_idx],
        model="kokoro",
        voice="af_heart",
        synthesis_mode="server",
    )

    # Should receive an error message
    import asyncio

    await asyncio.sleep(0.5)  # Wait for message

    error_msgs = [m for m in regular_ws_client.messages if m.get("type") == "error"]
    assert len(error_msgs) > 0
    assert "insufficient credits" in error_msgs[0]["error"].lower()


@pytest.mark.asyncio
async def test_tts_with_credits_deduction(regular_user, admin_client, regular_client, unique_document):
    """Test that TTS works with credits and deducts them properly via WS."""
    # Grant 100 credits to the user using admin API
    initial_credits = Decimal("100.0")
    await grant_credits_via_api(admin_client, regular_user["id"], initial_credits)

    document_id = unique_document["id"]
    block_idx = unique_document["blocks"][0]["idx"]

    # Create WS client for regular user
    ws_client = await make_ws_client(regular_user["token"])

    try:
        await ws_client.synthesize(
            document_id=document_id,
            block_indices=[block_idx],
            model="kokoro",
            voice="af_heart",
            synthesis_mode="server",
        )

        # Wait for synthesis to complete
        cached_msg = await ws_client.wait_for_status(block_idx, "cached", timeout=120.0)
        assert cached_msg is not None, "Synthesis timed out"
        audio_url = cached_msg["audio_url"]

        # Fetch audio to verify it exists
        audio_response = await regular_client.get(audio_url)
        assert audio_response.status_code == 200
        assert len(audio_response.content) > 0

        # Verify credits were deducted via API
        credits_after = await get_user_credits_via_api(regular_client)
        final_balance = Decimal(credits_after["balance"])
        assert final_balance < initial_credits

        # Verify transaction was created via API
        tx_response = await regular_client.get("/v1/users/me/transactions")
        assert tx_response.status_code == 200
        transactions = tx_response.json()

        # Find the usage deduction transaction
        usage_tx = next((tx for tx in transactions if tx["type"] == "usage_deduction"), None)
        assert usage_tx is not None
        assert Decimal(usage_tx["amount"]) < 0  # Should be negative (deduction)
    finally:
        await ws_client.close()


@pytest.mark.asyncio
async def test_tts_cached_no_credit_deduction(regular_user, admin_client, regular_client, unique_document):
    """Test that cached audio doesn't deduct credits again via WS."""
    # Grant credits
    initial_credits = Decimal("100.0")
    await grant_credits_via_api(admin_client, regular_user["id"], initial_credits)

    document_id = unique_document["id"]
    block_idx = unique_document["blocks"][0]["idx"]

    ws_client = await make_ws_client(regular_user["token"])

    try:
        # First synthesis - should deduct credits
        await ws_client.synthesize(
            document_id=document_id,
            block_indices=[block_idx],
            model="kokoro",
            voice="af_heart",
            synthesis_mode="server",
        )

        cached_msg = await ws_client.wait_for_status(block_idx, "cached", timeout=120.0)
        assert cached_msg is not None
        first_audio_url = cached_msg["audio_url"]

        # Check balance after first synthesis
        credits_after_first = await get_user_credits_via_api(regular_client)
        balance_after_first = Decimal(credits_after_first["balance"])
        assert balance_after_first < initial_credits

        # Second synthesis (same params) - should use cache
        ws_client.messages.clear()
        await ws_client.synthesize(
            document_id=document_id,
            block_indices=[block_idx],
            model="kokoro",
            voice="af_heart",
            synthesis_mode="server",
        )

        # Should immediately get cached status
        cached_msg2 = await ws_client.wait_for_status(block_idx, "cached", timeout=5.0)
        assert cached_msg2 is not None
        assert cached_msg2["audio_url"] == first_audio_url

        # Verify no additional credits were deducted
        credits_after_second = await get_user_credits_via_api(regular_client)
        balance_after_second = Decimal(credits_after_second["balance"])
        assert balance_after_second == balance_after_first  # No change

        # Verify only one usage transaction exists
        tx_response = await regular_client.get("/v1/users/me/transactions")
        assert tx_response.status_code == 200
        transactions = tx_response.json()

        usage_txs = [tx for tx in transactions if tx["type"] == "usage_deduction"]
        assert len(usage_txs) == 1  # Only one deduction
    finally:
        await ws_client.close()


@pytest.mark.asyncio
async def test_tts_admin_no_credit_check(admin_ws_client, admin_client, test_document):
    """Test that admins don't need credits via WS."""
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

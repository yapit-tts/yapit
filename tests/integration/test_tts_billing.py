"""Integration tests for TTS with billing/credits."""

from decimal import Decimal

import pytest


async def grant_credits_via_api(admin_client, user_id: str, amount: Decimal):
    """Grant credits to a user using the admin API."""
    response = await admin_client.post(
        f"/v1/admin/users/{user_id}/credits",
        json={
            "amount": str(amount),  # Convert Decimal to string for JSON
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
async def test_tts_insufficient_credits(regular_client, regular_document):
    """Test that TTS fails with 402 when user has no credits."""
    document_id = regular_document["id"]
    block_id = regular_document["blocks"][0]["id"]

    synth_response = await regular_client.post(
        f"/v1/documents/{document_id}/blocks/{block_id}/synthesize",
        json={"model_slug": "kokoro-cpu", "voice_slug": "af_heart", "speed": 1.0},
    )

    assert synth_response.status_code == 402
    error_data = synth_response.json()
    assert "insufficient credits" in error_data["detail"].lower()


@pytest.mark.asyncio
async def test_tts_with_credits_deduction(regular_client, admin_client, regular_user, unique_document):
    """Test that TTS works with credits and deducts them properly."""
    # Grant 100 credits to the user using admin API
    initial_credits = Decimal("100.0")
    await grant_credits_via_api(admin_client, regular_user["id"], initial_credits)

    document_id = unique_document["id"]
    block_id = unique_document["blocks"][0]["id"]

    synth_response = await regular_client.post(
        f"/v1/documents/{document_id}/blocks/{block_id}/synthesize",
        json={"model_slug": "kokoro-cpu", "voice_slug": "af_heart", "speed": 1.0},
    )

    assert synth_response.status_code == 200
    assert "audio/" in synth_response.headers["content-type"]
    assert len(synth_response.content) > 0

    # Get duration from response header
    duration_ms = int(synth_response.headers["X-Duration-Ms"])
    assert duration_ms > 0

    # Verify credits were deducted via API
    credits_after = await get_user_credits_via_api(regular_client)
    final_balance = Decimal(credits_after["balance"])
    assert final_balance < initial_credits

    # Calculate expected deduction (duration_seconds * credit_multiplier)
    # For kokoro-cpu, multiplier is 1.0
    expected_deduction = Decimal(duration_ms) / 1000 * Decimal("1.0")
    assert initial_credits - final_balance == expected_deduction

    # Verify transaction was created via API
    tx_response = await regular_client.get("/v1/users/me/transactions")
    assert tx_response.status_code == 200
    transactions = tx_response.json()

    # Find the usage deduction transaction
    usage_tx = next((tx for tx in transactions if tx["type"] == "usage_deduction"), None)
    assert usage_tx is not None
    assert Decimal(usage_tx["amount"]) == -expected_deduction


@pytest.mark.asyncio
async def test_tts_cached_no_credit_deduction(regular_client, admin_client, regular_user, unique_document):
    """Test that cached audio doesn't deduct credits again."""
    # Grant credits
    initial_credits = Decimal("100.0")
    await grant_credits_via_api(admin_client, regular_user["id"], initial_credits)

    document_id = unique_document["id"]
    block_id = unique_document["blocks"][0]["id"]

    # First synthesis - should deduct credits
    synth_params = {"model_slug": "kokoro-cpu", "voice_slug": "af_heart", "speed": 1.0}
    first_response = await regular_client.post(
        f"/v1/documents/{document_id}/blocks/{block_id}/synthesize",
        json=synth_params,
    )
    assert first_response.status_code == 200
    first_audio = first_response.content

    # Check balance after first synthesis
    credits_after_first = await get_user_credits_via_api(regular_client)
    balance_after_first = Decimal(credits_after_first["balance"])
    assert balance_after_first < initial_credits

    # Second synthesis (same params) - should use cache
    second_response = await regular_client.post(
        f"/v1/documents/{document_id}/blocks/{block_id}/synthesize",
        json=synth_params,
    )
    assert second_response.status_code == 200
    assert second_response.content == first_audio  # Same audio

    # Verify no additional credits were deducted
    credits_after_second = await get_user_credits_via_api(regular_client)
    balance_after_second = Decimal(credits_after_second["balance"])
    assert balance_after_second == balance_after_first  # No change

    # Verify only one transaction exists via API
    tx_response = await regular_client.get("/v1/users/me/transactions")
    assert tx_response.status_code == 200
    transactions = tx_response.json()

    # Count usage deduction transactions
    usage_txs = [tx for tx in transactions if tx["type"] == "usage_deduction"]
    assert len(usage_txs) == 1  # Only one deduction


@pytest.mark.asyncio
async def test_tts_admin_no_credit_check(admin_client, test_document):
    """Test that admins dont need any credits."""
    synth_response = await admin_client.post(
        f"/v1/documents/{test_document['id']}/blocks/{test_document['blocks'][0]['id']}/synthesize",
        json={"model_slug": "kokoro-cpu", "voice_slug": "af_heart", "speed": 1.0},
    )

    # Should succeed
    assert synth_response.status_code == 200
    assert "audio/" in synth_response.headers["content-type"]
    assert len(synth_response.content) > 0

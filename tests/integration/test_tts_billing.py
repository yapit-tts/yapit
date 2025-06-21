"""Integration tests for TTS with billing/credits."""

from decimal import Decimal

import httpx
import pytest
from sqlmodel import select

from tests.integration.conftest import admin_user, get_auth_token
from yapit.gateway.domain_models import CreditTransaction, TransactionType


async def grant_credits_via_api(admin_token: str, user_id: str, amount: Decimal):
    """Grant credits to a user using the admin API."""
    async with httpx.AsyncClient(
        base_url="http://localhost:8000", headers={"Authorization": f"Bearer {admin_token}"}
    ) as client:
        response = await client.post(
            f"/v1/admin/users/{user_id}/credits",
            json={
                "amount": str(amount),  # Convert Decimal to string for JSON
                "description": "Test credit grant",
                "type": "credit_bonus",
            },
        )
        assert response.status_code == 200
        return response.json()


async def get_user_credits_via_api(admin_token: str, user_id: str) -> dict:
    """Get user credits using the admin API."""
    async with httpx.AsyncClient(
        base_url="http://localhost:8000", headers={"Authorization": f"Bearer {admin_token}"}
    ) as client:
        response = await client.get(f"/v1/admin/users/{user_id}/credits")
        if response.status_code == 404:
            return {"balance": "0"}
        assert response.status_code == 200
        return response.json()


@pytest.mark.asyncio
async def test_tts_insufficient_credits(regular_user):
    """Test that TTS fails with 402 when user has no credits.

    Requires: gateway, postgres, redis, and kokoro worker running.
    """
    headers = {"Authorization": f"Bearer {regular_user['token']}"}

    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=10.0, headers=headers) as client:
        # Create document
        doc_response = await client.post(
            "/v1/documents", json={"source_type": "paste", "text_content": "Hello, I need credits!"}
        )
        assert doc_response.status_code == 201
        doc_data = doc_response.json()
        document_id = doc_data["document_id"]
        block_id = doc_data["blocks"][0]["id"]

        # Try to synthesize - should fail with 402
        synth_response = await client.post(
            f"/v1/documents/{document_id}/blocks/{block_id}/synthesize",
            json={"model_slug": "kokoro-cpu", "voice_slug": "af_heart", "speed": 1.0},
        )

        assert synth_response.status_code == 402
        error_data = synth_response.json()
        assert "insufficient credits" in error_data["detail"].lower()


@pytest.mark.asyncio
async def test_tts_with_credits_deduction(regular_user, admin_user):
    """Test that TTS works with credits and deducts them properly.

    Requires: gateway, postgres, redis, and kokoro worker running.
    """
    # Grant 100 credits to the user using admin API
    initial_credits = Decimal("100.0")
    await grant_credits_via_api(admin_user["token"], regular_user["id"], initial_credits)

    headers = {"Authorization": f"Bearer {regular_user['token']}"}

    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=70.0, headers=headers) as client:
        # Create document with unique text to avoid cache
        import time

        unique_text = f"Hello with credits! Test at {time.time()}"
        doc_response = await client.post("/v1/documents", json={"source_type": "paste", "text_content": unique_text})
        assert doc_response.status_code == 201
        doc_data = doc_response.json()
        document_id = doc_data["document_id"]
        block_id = doc_data["blocks"][0]["id"]

        # Synthesize - should work
        synth_response = await client.post(
            f"/v1/documents/{document_id}/blocks/{block_id}/synthesize",
            json={"model_slug": "kokoro-cpu", "voice_slug": "af_heart", "speed": 1.0},
        )

        # Should succeed
        assert synth_response.status_code == 200
        assert "audio/" in synth_response.headers["content-type"]
        assert len(synth_response.content) > 0

        # Get duration from response header
        duration_ms = int(synth_response.headers["X-Duration-Ms"])
        assert duration_ms > 0

        # Verify credits were deducted via API
        credits_after = await get_user_credits_via_api(admin_user["token"], regular_user["id"])
        final_balance = Decimal(credits_after["balance"])
        assert final_balance < initial_credits

        # Calculate expected deduction (duration_seconds * credit_multiplier)
        # For kokoro-cpu, multiplier is 1.0
        expected_deduction = Decimal(duration_ms) / 1000 * Decimal("1.0")
        assert abs((initial_credits - final_balance) - expected_deduction) < Decimal(
            "0.0001"
        )  # Allow small float precision diff

        # Verify transaction was created via API
        async with httpx.AsyncClient(
            base_url="http://localhost:8000", headers={"Authorization": f"Bearer {admin_user['token']}"}
        ) as client:
            tx_response = await client.get(f"/v1/admin/users/{regular_user['id']}/credit-transactions")
            assert tx_response.status_code == 200
            transactions = tx_response.json()

            # Find the usage deduction transaction
            usage_tx = next((tx for tx in transactions if tx["type"] == "usage_deduction"), None)
            assert usage_tx is not None
            assert Decimal(usage_tx["amount"]) == -expected_deduction


@pytest.mark.asyncio
async def test_tts_cached_no_credit_deduction(regular_user, admin_user):
    """Test that cached audio doesn't deduct credits again.

    Requires: gateway, postgres, redis, and kokoro worker running.
    """
    # Grant credits
    initial_credits = Decimal("100.0")
    await grant_credits_via_api(admin_user["token"], regular_user["id"], initial_credits)

    headers = {"Authorization": f"Bearer {regular_user['token']}"}

    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=70.0, headers=headers) as client:
        # Create document with unique text to ensure fresh synthesis
        import time

        unique_text = f"Cache test content {time.time()}"
        doc_response = await client.post("/v1/documents", json={"source_type": "paste", "text_content": unique_text})
        assert doc_response.status_code == 201
        doc_data = doc_response.json()
        document_id = doc_data["document_id"]
        block_id = doc_data["blocks"][0]["id"]

        # First synthesis - should deduct credits
        synth_params = {"model_slug": "kokoro-cpu", "voice_slug": "af_heart", "speed": 1.0}
        first_response = await client.post(
            f"/v1/documents/{document_id}/blocks/{block_id}/synthesize",
            json=synth_params,
        )
        assert first_response.status_code == 200
        first_audio = first_response.content

        # Check balance after first synthesis
        credits_after_first = await get_user_credits_via_api(admin_user["token"], regular_user["id"])
        balance_after_first = Decimal(credits_after_first["balance"])
        assert balance_after_first < initial_credits

        # Second synthesis (same params) - should use cache
        second_response = await client.post(
            f"/v1/documents/{document_id}/blocks/{block_id}/synthesize",
            json=synth_params,
        )
        assert second_response.status_code == 200
        assert second_response.content == first_audio  # Same audio

        # Verify no additional credits were deducted
        credits_after_second = await get_user_credits_via_api(admin_user["token"], regular_user["id"])
        balance_after_second = Decimal(credits_after_second["balance"])
        assert balance_after_second == balance_after_first  # No change

        # Verify only one transaction exists via API
        async with httpx.AsyncClient(
            base_url="http://localhost:8000", headers={"Authorization": f"Bearer {admin_user['token']}"}
        ) as admin_client:
            tx_response = await admin_client.get(f"/v1/admin/users/{regular_user['id']}/credit-transactions")
            assert tx_response.status_code == 200
            transactions = tx_response.json()

            # Count usage deduction transactions
            usage_txs = [tx for tx in transactions if tx["type"] == "usage_deduction"]
            assert len(usage_txs) == 1  # Only one deduction


@pytest.mark.asyncio
async def test_tts_admin_no_credit_check(admin_user):
    """Test that admins bypass credit checks entirely.

    Requires: gateway, postgres, redis, and kokoro worker running.
    """
    headers = {"Authorization": f"Bearer {admin_user['token']}"}

    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=70.0, headers=headers) as client:
        # Create document
        doc_response = await client.post(
            "/v1/documents", json={"source_type": "paste", "text_content": "Admin test - no credits needed"}
        )
        assert doc_response.status_code == 201
        doc_data = doc_response.json()

        # Synthesize - should work even without any credits
        synth_response = await client.post(
            f"/v1/documents/{doc_data['document_id']}/blocks/{doc_data['blocks'][0]['id']}/synthesize",
            json={"model_slug": "kokoro-cpu", "voice_slug": "af_heart", "speed": 1.0},
        )

        # Should succeed
        assert synth_response.status_code == 200
        assert "audio/" in synth_response.headers["content-type"]
        assert len(synth_response.content) > 0

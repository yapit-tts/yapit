"""Test admin credit management endpoints."""

from decimal import Decimal

import pytest
from fastapi import status

from tests.yapit.gateway.api.conftest import ADMIN_USER, TEST_USER
from yapit.gateway.domain_models import UserCredits


@pytest.mark.asyncio
async def test_admin_can_grant_credits(client, app, session):
    """Test that admin can grant credits to a user."""
    from yapit.gateway.auth import authenticate

    app.dependency_overrides[authenticate] = lambda: ADMIN_USER

    # Grant credits
    response = await client.post(
        f"/v1/admin/users/{TEST_USER.id}/credits",
        json={"amount": "100.50", "description": "Test credit grant", "type": "credit_bonus"},
    )
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert data["user_id"] == TEST_USER.id
    assert Decimal(data["balance"]) == Decimal("100.50")
    assert Decimal(data["total_purchased"]) == Decimal("100.50")


@pytest.mark.asyncio
async def test_admin_can_deduct_credits(client, app, session):
    """Test that admin can deduct credits from a user."""
    from yapit.gateway.auth import authenticate

    app.dependency_overrides[authenticate] = lambda: ADMIN_USER

    # First grant some credits
    user_credits = UserCredits(
        user_id=TEST_USER.id,
        balance=Decimal("100"),
        total_purchased=Decimal("100"),
        total_used=Decimal("0"),
    )
    session.add(user_credits)
    await session.commit()

    # Deduct credits
    response = await client.post(
        f"/v1/admin/users/{TEST_USER.id}/credits",
        json={"amount": "-25.75", "description": "Manual deduction", "type": "credit_adjustment"},
    )
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert Decimal(data["balance"]) == Decimal("74.25")


@pytest.mark.asyncio
async def test_admin_can_get_user_credits(client, app, session):
    """Test that admin can get user credit balance."""
    from yapit.gateway.auth import authenticate

    app.dependency_overrides[authenticate] = lambda: ADMIN_USER

    # Create credits
    user_credits = UserCredits(
        user_id=TEST_USER.id,
        balance=Decimal("50.25"),
        total_purchased=Decimal("100"),
        total_used=Decimal("49.75"),
    )
    session.add(user_credits)
    await session.commit()

    # Get credits
    response = await client.get(f"/v1/admin/users/{TEST_USER.id}/credits")
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert data["user_id"] == TEST_USER.id
    assert Decimal(data["balance"]) == Decimal("50.25")
    assert Decimal(data["total_purchased"]) == Decimal("100")
    assert Decimal(data["total_used"]) == Decimal("49.75")


@pytest.mark.asyncio
async def test_regular_user_cannot_access_credit_endpoints(client, app):
    """Test that regular users cannot access admin credit endpoints."""
    from yapit.gateway.auth import authenticate

    app.dependency_overrides[authenticate] = lambda: TEST_USER

    # Try to grant credits
    response = await client.post(
        f"/v1/admin/users/{TEST_USER.id}/credits",
        json={"amount": "100", "description": "Unauthorized attempt", "type": "credit_bonus"},
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN

    # Try to get credits
    response = await client.get(f"/v1/admin/users/{TEST_USER.id}/credits")
    assert response.status_code == status.HTTP_403_FORBIDDEN

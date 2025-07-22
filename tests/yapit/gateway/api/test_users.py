"""Test user API endpoints."""

from decimal import Decimal

import pytest
from fastapi import status

from yapit.gateway.auth import authenticate
from yapit.gateway.domain_models import (
    CreditTransaction,
    TransactionStatus,
    TransactionType,
    UserCredits,
)


@pytest.mark.asyncio
async def test_user_can_get_own_credits(client, app, test_user, session):
    """Test that users can get their own credit balance."""
    # Set test user auth
    app.dependency_overrides[authenticate] = lambda: test_user

    # Create credits
    user_credits = UserCredits(
        user_id=test_user.id,
        balance=Decimal("50.25"),
        total_purchased=Decimal("100"),
        total_used=Decimal("49.75"),
    )
    session.add(user_credits)
    await session.commit()

    # Get credits
    response = await client.get("/v1/users/me/credits")
    assert response.status_code == status.HTTP_200_OK

    data = UserCredits.model_validate(response.json())
    assert data.user_id == test_user.id
    assert data.balance == Decimal("50.25")
    assert data.total_purchased == Decimal("100")
    assert data.total_used == Decimal("49.75")


@pytest.mark.asyncio
async def test_user_can_get_own_transactions(client, app, test_user, session):
    """Test that users can get their own transaction history."""
    # Set test user auth
    app.dependency_overrides[authenticate] = lambda: test_user

    # First create user credits record (required for foreign key)
    user_credits = UserCredits(
        user_id=test_user.id,
        balance=Decimal("90"),
        total_purchased=Decimal("100"),
        total_used=Decimal("10"),
    )
    session.add(user_credits)
    await session.commit()

    # Create some transactions
    transactions = [
        CreditTransaction(
            user_id=test_user.id,
            type=TransactionType.credit_purchase,
            status=TransactionStatus.completed,
            amount=Decimal("100"),
            balance_before=Decimal("0"),
            balance_after=Decimal("100"),
            description="Initial purchase",
        ),
        CreditTransaction(
            user_id=test_user.id,
            type=TransactionType.usage_deduction,
            status=TransactionStatus.completed,
            amount=Decimal("-10"),
            balance_before=Decimal("100"),
            balance_after=Decimal("90"),
            description="TTS usage",
        ),
    ]
    for t in transactions:
        session.add(t)
    await session.commit()

    # Get transactions
    response = await client.get("/v1/users/me/transactions")
    assert response.status_code == status.HTTP_200_OK

    transactions = [CreditTransaction.model_validate(t) for t in response.json()]
    assert len(transactions) == 2
    # Should be ordered by created desc
    assert transactions[0].amount == Decimal("-10")  # Most recent first
    assert transactions[1].amount == Decimal("100")


@pytest.mark.asyncio
async def test_user_cannot_view_other_users_filters(client, app, test_user, admin_user):
    """Test that users cannot view other users' filters."""
    # Set test user auth
    app.dependency_overrides[authenticate] = lambda: test_user

    # Try to get admin user's filters
    response = await client.get(f"/v1/users/{admin_user.id}/filters")
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert "Cannot view other users' filters" in response.json()["detail"]


@pytest.mark.asyncio
async def test_user_can_view_own_filters(client, app, test_user):
    """Test that users can view their own filters."""
    # Set test user auth
    app.dependency_overrides[authenticate] = lambda: test_user

    # Get own filters (should be empty list)
    response = await client.get(f"/v1/users/{test_user.id}/filters")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == []


@pytest.mark.asyncio
async def test_credits_not_found_for_new_user(client, app, test_user):
    """Test that appropriate error is returned when user has no credit record."""
    # Set test user auth
    app.dependency_overrides[authenticate] = lambda: test_user

    # Get credits without any record
    response = await client.get("/v1/users/me/credits")
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["resource_type"] == "UserCredits"
    assert response.json()["resource_id"] == test_user.id

"""Test user API endpoints."""

import pytest
from fastapi import status

from yapit.gateway.auth import authenticate


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


# TODO: Add subscription/usage tests
# - test_user_can_get_subscription
# - test_user_can_get_usage_summary
# - test_free_user_has_no_subscription

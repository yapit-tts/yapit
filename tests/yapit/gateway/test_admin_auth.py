"""Test admin authentication separately."""

import pytest
from fastapi import HTTPException

from yapit.gateway.deps import require_admin
from yapit.gateway.stack_auth.users import User, UserServerMetadata


@pytest.mark.asyncio
async def test_require_admin_with_admin_user():
    """Test that admin users pass the require_admin check."""
    admin_user = User(
        id="admin-123",
        primary_email_verified=True,
        primary_email_auth_enabled=True,
        signed_up_at_millis=1234567890,
        last_active_at_millis=1234567890,
        is_anonymous=False,
        primary_email="admin@example.com",
        server_metadata=UserServerMetadata(is_admin=True),
    )

    # Should not raise
    result = await require_admin(admin_user)
    assert result == admin_user


@pytest.mark.asyncio
async def test_require_admin_with_regular_user():
    """Test that regular users are rejected by require_admin."""
    regular_user = User(
        id="user-123",
        primary_email_verified=True,
        primary_email_auth_enabled=True,
        signed_up_at_millis=1234567890,
        last_active_at_millis=1234567890,
        is_anonymous=False,
        primary_email="user@example.com",
        server_metadata=UserServerMetadata(is_admin=False),
    )

    with pytest.raises(HTTPException) as exc_info:
        await require_admin(regular_user)

    assert exc_info.value.status_code == 403
    assert "Admin access required" in exc_info.value.detail


@pytest.mark.asyncio
async def test_require_admin_with_no_metadata():
    """Test that users without server metadata are rejected."""
    user_no_metadata = User(
        id="user-456",
        primary_email_verified=True,
        primary_email_auth_enabled=True,
        signed_up_at_millis=1234567890,
        last_active_at_millis=1234567890,
        is_anonymous=False,
        primary_email="user@example.com",
        server_metadata=None,
    )

    with pytest.raises(HTTPException) as exc_info:
        await require_admin(user_no_metadata)

    assert exc_info.value.status_code == 403
    assert "Admin access required" in exc_info.value.detail

"""Test user API endpoints."""

import pytest
from fastapi import status

from yapit.gateway.auth import authenticate
from yapit.gateway.domain_models import Block, Document


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


# Preferences tests


@pytest.mark.asyncio
async def test_get_preferences_empty(client, as_test_user):
    """Test getting preferences when none exist."""
    response = await client.get("/v1/users/me/preferences")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"pinned_voices": []}


@pytest.mark.asyncio
async def test_update_preferences(client, as_test_user):
    """Test updating preferences."""
    response = await client.patch(
        "/v1/users/me/preferences",
        json={"pinned_voices": ["kokoro:af_heart", "kokoro:am_fenrir"]},
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["pinned_voices"] == ["kokoro:af_heart", "kokoro:am_fenrir"]

    # Verify persistence
    response = await client.get("/v1/users/me/preferences")
    assert response.json()["pinned_voices"] == ["kokoro:af_heart", "kokoro:am_fenrir"]


@pytest.mark.asyncio
async def test_update_preferences_overwrites(client, as_test_user):
    """Test that updating preferences overwrites the list."""
    await client.patch("/v1/users/me/preferences", json={"pinned_voices": ["voice1"]})
    response = await client.patch("/v1/users/me/preferences", json={"pinned_voices": ["voice2"]})
    assert response.json()["pinned_voices"] == ["voice2"]


# Stats tests


@pytest.mark.asyncio
async def test_get_stats_empty(client, as_test_user):
    """Test getting stats with no documents."""
    response = await client.get("/v1/users/me/stats")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["total_audio_ms"] == 0
    assert data["total_characters"] == 0
    assert data["document_count"] == 0


@pytest.mark.asyncio
async def test_get_stats_with_documents(client, as_test_user, session, test_user):
    """Test getting stats with documents and blocks."""
    doc = Document(
        user_id=test_user.id,
        title="Test Doc",
        original_text="Hello world",
        structured_content="{}",
    )
    session.add(doc)
    await session.flush()

    block1 = Block(document=doc, idx=0, text="Hello world", est_duration_ms=1000)
    block2 = Block(document=doc, idx=1, text="Testing stats", est_duration_ms=2000)
    session.add(block1)
    session.add(block2)
    await session.commit()

    response = await client.get("/v1/users/me/stats")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["total_audio_ms"] == 3000
    assert data["total_characters"] == len("Hello world") + len("Testing stats")
    assert data["document_count"] == 1

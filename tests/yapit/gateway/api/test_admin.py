"""Test admin API endpoints."""

from decimal import Decimal

import pytest
from fastapi import status
from sqlmodel import select

from yapit.gateway.auth import authenticate
from yapit.gateway.domain_models import TTSModel, UserCredits, Voice


@pytest.mark.asyncio
async def test_admin_access_denied_for_regular_user(client, as_test_user):
    """Test that regular users cannot access admin endpoints."""
    response = await client.get("/v1/admin/filters")
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert "Admin access required" in response.json()["detail"]


@pytest.mark.asyncio
async def test_admin_can_create_model(client, as_admin_user, session):
    """Test that admin can create a new TTS model."""
    model_data = {
        "slug": "test-model",
        "name": "Test Model",
        "credit_multiplier": 2.0,
        "native_codec": "pcm",
        "sample_rate": 24000,
        "channels": 1,
        "sample_width": 2,
    }

    response = await client.post("/v1/admin/models", json=model_data)
    assert response.status_code == status.HTTP_201_CREATED

    created_model = response.json()
    assert created_model["slug"] == "test-model"
    assert created_model["name"] == "Test Model"

    # Verify in database
    db_model = (await session.exec(select(TTSModel).where(TTSModel.slug == "test-model"))).first()
    assert db_model is not None
    assert float(db_model.credit_multiplier) == 2.0


@pytest.mark.asyncio
async def test_admin_can_update_model(client, as_admin_user, session):
    """Test that admin can update an existing model."""
    # First create a model
    model = TTSModel(
        slug="update-test",
        name="Original Name",
        credit_multiplier=1.0,
        native_codec="pcm",
        sample_rate=24000,
        channels=1,
        sample_width=2,
    )
    session.add(model)
    await session.commit()

    # Update it
    update_data = {"name": "Updated Name", "credit_multiplier": 3.0}
    response = await client.put(f"/v1/admin/models/{model.slug}", json=update_data)
    assert response.status_code == status.HTTP_200_OK

    updated_model = response.json()
    assert updated_model["name"] == "Updated Name"
    assert float(updated_model["credit_multiplier"]) == 3.0


@pytest.mark.asyncio
async def test_admin_can_manage_voices(client, as_admin_user, session):
    """Test admin can create, update, and delete voices."""
    # First create a model
    model = TTSModel(
        slug="voice-test-model",
        name="Voice Test Model",
        credit_multiplier=1.0,
        native_codec="pcm",
        sample_rate=24000,
        channels=1,
        sample_width=2,
    )
    session.add(model)
    await session.commit()

    # Create a voice
    voice_data = {
        "slug": "test-voice",
        "name": "Test Voice",
        "lang": "en-us",
        "description": "A test voice",
    }

    response = await client.post(f"/v1/admin/models/{model.slug}/voices", json=voice_data)
    assert response.status_code == status.HTTP_201_CREATED
    created_voice = response.json()
    assert created_voice["slug"] == "test-voice"
    assert created_voice["name"] == "Test Voice"

    # Update the voice
    update_data = {
        "name": "Updated Voice Name",
        "description": "Updated description",
    }
    response = await client.put(f"/v1/admin/models/{model.slug}/voices/test-voice", json=update_data)
    assert response.status_code == status.HTTP_200_OK
    updated_voice = response.json()
    assert updated_voice["name"] == "Updated Voice Name"
    assert updated_voice["description"] == "Updated description"

    # Delete the voice
    response = await client.delete(f"/v1/admin/models/{model.slug}/voices/test-voice")
    assert response.status_code == status.HTTP_204_NO_CONTENT

    # Verify voice is deleted
    db_voice = (await session.exec(select(Voice).where(Voice.slug == "test-voice"))).first()
    assert db_voice is None


@pytest.mark.asyncio
async def test_admin_voice_creation_duplicate_check(client, as_admin_user, session):
    """Test that duplicate voice slugs are rejected for the same model."""
    # Create a model
    model = TTSModel(
        slug="duplicate-voice-test",
        name="Duplicate Voice Test",
        credit_multiplier=1.0,
        native_codec="pcm",
        sample_rate=24000,
        channels=1,
        sample_width=2,
    )
    session.add(model)
    await session.commit()

    # Create first voice
    voice_data = {
        "slug": "duplicate-test",
        "name": "First Voice",
        "lang": "en",
    }

    response = await client.post(f"/v1/admin/models/{model.slug}/voices", json=voice_data)
    assert response.status_code == status.HTTP_201_CREATED

    # Try to create duplicate
    voice_data["name"] = "Second Voice"
    response = await client.post(f"/v1/admin/models/{model.slug}/voices", json=voice_data)
    assert response.status_code == status.HTTP_409_CONFLICT
    assert "already exists" in response.json()["detail"]


@pytest.mark.asyncio
async def test_admin_can_delete_model_with_voices(client, as_admin_user, session):
    """Test that deleting a model also deletes its voices (cascade)."""
    # Create model with voices
    model = TTSModel(
        slug="delete-test",
        name="Delete Test",
        credit_multiplier=1.0,
        native_codec="pcm",
        sample_rate=24000,
        channels=1,
        sample_width=2,
    )
    session.add(model)
    await session.commit()

    voice = Voice(
        slug="test-voice",
        name="Test Voice",
        lang="en",
        model_id=model.id,
    )
    session.add(voice)
    await session.commit()

    # Delete model
    response = await client.delete(f"/v1/admin/models/{model.slug}")
    assert response.status_code == status.HTTP_204_NO_CONTENT

    # Verify model and voice are deleted
    db_model = (await session.exec(select(TTSModel).where(TTSModel.slug == "delete-test"))).first()
    assert db_model is None

    db_voice = (await session.exec(select(Voice).where(Voice.slug == "test-voice"))).first()
    assert db_voice is None


@pytest.mark.asyncio
async def test_admin_can_manage_system_filters(client, as_admin_user, session):
    """Test admin can create, update, and delete system filters."""
    # Create system filter
    filter_data = {
        "name": "Test System Filter",
        "description": "A test filter",
        "config": {"regex_rules": [{"pattern": "test", "replacement": "TEST"}], "llm": {}},
    }

    response = await client.post("/v1/admin/filters", json=filter_data)
    assert response.status_code == status.HTTP_201_CREATED
    filter_id = response.json()["id"]

    # List system filters
    response = await client.get("/v1/admin/filters")
    assert response.status_code == status.HTTP_200_OK
    filters = response.json()
    assert any(f["name"] == "Test System Filter" for f in filters)

    # Update filter
    update_data = {"description": "Updated description"}
    response = await client.put(f"/v1/admin/filters/{filter_id}", json=update_data)
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["description"] == "Updated description"

    # Delete filter
    response = await client.delete(f"/v1/admin/filters/{filter_id}")
    assert response.status_code == status.HTTP_204_NO_CONTENT


# Credit Management Tests


@pytest.mark.asyncio
async def test_admin_can_grant_credits(client, app, admin_user, test_user, session):
    """Test that admin can grant credits to a user."""
    # Set admin auth
    app.dependency_overrides[authenticate] = lambda: admin_user

    # Grant credits
    response = await client.post(
        f"/v1/admin/users/{test_user.id}/credits",
        json={"amount": "100.50", "description": "Test credit grant", "type": "credit_bonus"},
    )
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert data["user_id"] == test_user.id
    assert Decimal(data["balance"]) == Decimal("100.50")
    assert Decimal(data["total_purchased"]) == Decimal("100.50")


@pytest.mark.asyncio
async def test_admin_can_deduct_credits(client, app, admin_user, test_user, session):
    """Test that admin can deduct credits from a user."""
    # Set admin auth
    app.dependency_overrides[authenticate] = lambda: admin_user

    # First grant some credits
    user_credits = UserCredits(
        user_id=test_user.id,
        balance=Decimal("100"),
        total_purchased=Decimal("100"),
        total_used=Decimal("0"),
    )
    session.add(user_credits)
    await session.commit()

    # Deduct credits
    response = await client.post(
        f"/v1/admin/users/{test_user.id}/credits",
        json={"amount": "-25.75", "description": "Manual deduction", "type": "credit_adjustment"},
    )
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert Decimal(data["balance"]) == Decimal("74.25")


@pytest.mark.asyncio
async def test_admin_can_get_user_credits(client, app, admin_user, test_user, session):
    """Test that admin can get user credit balance."""
    # Set admin auth
    app.dependency_overrides[authenticate] = lambda: admin_user

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
    response = await client.get(f"/v1/admin/users/{test_user.id}/credits")
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert data["user_id"] == test_user.id
    assert Decimal(data["balance"]) == Decimal("50.25")
    assert Decimal(data["total_purchased"]) == Decimal("100")
    assert Decimal(data["total_used"]) == Decimal("49.75")


@pytest.mark.asyncio
async def test_regular_user_cannot_access_credit_endpoints(client, as_test_user):
    """Test that regular users cannot access admin credit endpoints."""
    # Try to grant credits
    response = await client.post(
        f"/v1/admin/users/{as_test_user.id}/credits",
        json={"amount": "100", "description": "Unauthorized attempt", "type": "credit_bonus"},
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN

    # Try to get credits
    response = await client.get(f"/v1/admin/users/{as_test_user.id}/credits")
    assert response.status_code == status.HTTP_403_FORBIDDEN

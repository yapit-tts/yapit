"""Test admin API endpoints."""

import pytest
from fastapi import status
from sqlmodel import select

from yapit.gateway.domain_models import TTSModel, Voice


@pytest.mark.asyncio
async def test_admin_can_create_model(client, as_admin_user, session):
    """Test that admin can create a new TTS model."""
    model_data = {
        "slug": "test-model",
        "name": "Test Model",
        "native_codec": "pcm",
        "sample_rate": 24000,
        "channels": 1,
        "sample_width": 2,
    }

    response = await client.post("/v1/admin/models", json=model_data)
    assert response.status_code == status.HTTP_201_CREATED

    created_model = TTSModel.model_validate(response.json())
    assert created_model.slug == "test-model"
    assert created_model.name == "Test Model"

    # Verify in database
    db_model = (await session.exec(select(TTSModel).where(TTSModel.slug == "test-model"))).first()
    assert db_model is not None


@pytest.mark.asyncio
async def test_admin_can_update_model(client, as_admin_user, session):
    """Test that admin can update an existing model."""
    # First create a model
    model = TTSModel(
        slug="update-test",
        name="Original Name",
        native_codec="pcm",
        sample_rate=24000,
        channels=1,
        sample_width=2,
    )
    session.add(model)
    await session.commit()

    # Update it
    update_data = {"name": "Updated Name"}
    response = await client.put(f"/v1/admin/models/{model.slug}", json=update_data)
    assert response.status_code == status.HTTP_200_OK

    updated_model = TTSModel.model_validate(response.json())
    assert updated_model.name == "Updated Name"


@pytest.mark.asyncio
async def test_admin_can_manage_voices(client, as_admin_user, session):
    """Test admin can create, update, and delete voices."""
    # First create a model
    model = TTSModel(
        slug="voice-test-model",
        name="Voice Test Model",
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
    created_voice = Voice.model_validate(response.json())
    assert created_voice.slug == "test-voice"
    assert created_voice.name == "Test Voice"

    # Update the voice
    update_data = {
        "name": "Updated Voice Name",
        "description": "Updated description",
    }
    response = await client.put(f"/v1/admin/models/{model.slug}/voices/test-voice", json=update_data)
    assert response.status_code == status.HTTP_200_OK
    updated_voice = Voice.model_validate(response.json())
    assert updated_voice.name == "Updated Voice Name"
    assert updated_voice.description == "Updated description"

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

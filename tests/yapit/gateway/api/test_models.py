"""Test models API endpoints."""

import pytest
from fastapi import status

from yapit.gateway.api.v1.models import ModelRead, VoiceRead
from yapit.gateway.domain_models import TTSModel, Voice


@pytest.mark.asyncio
async def test_list_models(client, as_test_user, session):
    """Test listing all available TTS models."""
    model = TTSModel(
        slug="test-model",
        name="Test Model",
        description="A test model",
    )
    voice = Voice(
        slug="test-voice",
        name="Test Voice",
        lang="en-us",
        description="A test voice",
        model=model,
    )
    session.add(model)
    session.add(voice)
    await session.commit()

    response = await client.get("/v1/models")
    assert response.status_code == status.HTTP_200_OK

    models = [ModelRead.model_validate(m) for m in response.json()]
    assert len(models) > 0
    test_model = next((m for m in models if m.slug == "test-model"), None)
    assert test_model is not None
    assert test_model.name == "Test Model"
    assert len(test_model.voices) > 0
    assert test_model.voices[0].slug == "test-voice"


@pytest.mark.asyncio
async def test_read_model(client, as_test_user, session):
    """Test reading a specific TTS model by slug."""
    model = TTSModel(
        slug="test-model-read",
        name="Test Model Read",
    )
    session.add(model)
    await session.commit()

    response = await client.get(f"/v1/models/{model.slug}")
    assert response.status_code == status.HTTP_200_OK

    model = ModelRead.model_validate(response.json())
    assert model.slug == "test-model-read"
    assert model.name == "Test Model Read"


@pytest.mark.asyncio
async def test_read_model_not_found(client, as_test_user):
    """Test reading a non-existent TTS model."""
    response = await client.get("/v1/models/non-existent-model")
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_list_voices(client, as_test_user, session):
    """Test listing voices for a specific model."""
    model = TTSModel(
        slug="voice-model",
        name="Voice Model",
    )
    voice1 = Voice(slug="voice1", name="Voice 1", lang="en", model=model)
    voice2 = Voice(slug="voice2", name="Voice 2", lang="fr", model=model)
    session.add(model)
    session.add(voice1)
    session.add(voice2)
    await session.commit()

    response = await client.get(f"/v1/models/{model.slug}/voices")
    assert response.status_code == status.HTTP_200_OK

    voices = [VoiceRead.model_validate(v) for v in response.json()]
    assert len(voices) == 2
    assert voices[0].slug == "voice1"
    assert voices[1].slug == "voice2"


@pytest.mark.asyncio
async def test_list_voices_model_not_found(client, as_test_user):
    """Test listing voices for a non-existent model."""
    response = await client.get("/v1/models/non-existent-model/voices")
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_inactive_models_not_listed(client, as_test_user, session):
    """Test that inactive models are filtered from list."""
    active_model = TTSModel(
        slug="active-model",
        name="Active Model",
        is_active=True,
    )
    inactive_model = TTSModel(
        slug="inactive-model",
        name="Inactive Model",
        is_active=False,
    )
    session.add(active_model)
    session.add(inactive_model)
    await session.commit()

    response = await client.get("/v1/models")
    assert response.status_code == status.HTTP_200_OK

    slugs = [m["slug"] for m in response.json()]
    assert "active-model" in slugs
    assert "inactive-model" not in slugs


@pytest.mark.asyncio
async def test_inactive_voices_not_listed(client, as_test_user, session):
    """Test that inactive voices are filtered from model's voice list."""
    model = TTSModel(
        slug="model-with-voices",
        name="Model With Voices",
    )
    active_voice = Voice(slug="active-voice", name="Active", lang="en", model=model, is_active=True)
    inactive_voice = Voice(slug="inactive-voice", name="Inactive", lang="en", model=model, is_active=False)
    session.add(model)
    session.add(active_voice)
    session.add(inactive_voice)
    await session.commit()

    response = await client.get(f"/v1/models/{model.slug}/voices")
    assert response.status_code == status.HTTP_200_OK

    slugs = [v["slug"] for v in response.json()]
    assert "active-voice" in slugs
    assert "inactive-voice" not in slugs

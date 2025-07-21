"""Test models API endpoints."""

import pytest
from fastapi import status

from yapit.gateway.domain_models import TTSModel, Voice


@pytest.mark.asyncio
async def test_list_models(client, as_test_user, session):
    """Test listing all available TTS models."""
    # Create a dummy model with a voice
    model = TTSModel(
        slug="test-model",
        name="Test Model",
        credits_per_sec=0.01,
        description="A test model",
        sample_rate=24000,
        channels=1,
        sample_width=2,
        native_codec="pcm",
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

    models = response.json()
    assert isinstance(models, list)
    assert len(models) > 0
    test_model = next((m for m in models if m["slug"] == "test-model"), None)
    assert test_model is not None
    assert test_model["name"] == "Test Model"
    assert "voices" in test_model
    assert len(test_model["voices"]) > 0
    assert test_model["voices"][0]["slug"] == "test-voice"


@pytest.mark.asyncio
async def test_read_model(client, as_test_user, session):
    """Test reading a specific TTS model by slug."""
    model = TTSModel(
        slug="test-model-read",
        name="Test Model Read",
        credits_per_sec=0.02,
        sample_rate=24000,
        channels=1,
        sample_width=2,
        native_codec="pcm",
    )
    session.add(model)
    await session.commit()

    response = await client.get(f"/v1/models/{model.slug}")
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert data["slug"] == "test-model-read"
    assert data["name"] == "Test Model Read"
    assert data["credits_per_sec"] == 0.02


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
        credits_per_sec=0.01,
        sample_rate=24000,
        channels=1,
        sample_width=2,
        native_codec="pcm",
    )
    voice1 = Voice(slug="voice1", name="Voice 1", lang="en", model=model)
    voice2 = Voice(slug="voice2", name="Voice 2", lang="fr", model=model)
    session.add(model)
    session.add(voice1)
    session.add(voice2)
    await session.commit()

    response = await client.get(f"/v1/models/{model.slug}/voices")
    assert response.status_code == status.HTTP_200_OK

    voices = response.json()
    assert isinstance(voices, list)
    assert len(voices) == 2
    assert voices[0]["slug"] == "voice1"
    assert voices[1]["slug"] == "voice2"


@pytest.mark.asyncio
async def test_list_voices_model_not_found(client, as_test_user):
    """Test listing voices for a non-existent model."""
    response = await client.get("/v1/models/non-existent-model/voices")
    assert response.status_code == status.HTTP_404_NOT_FOUND

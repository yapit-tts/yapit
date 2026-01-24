from typing import List, cast

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlmodel import col, select

from yapit.gateway.auth import authenticate
from yapit.gateway.config import Settings, get_settings
from yapit.gateway.deps import AudioCache, AuthenticatedUser, CurrentTTSModel, CurrentVoice, DbSession, RedisClient
from yapit.gateway.domain_models import TTSModel
from yapit.gateway.synthesis import synthesize_and_wait

router = APIRouter(prefix="/v1/models", tags=["Models"])

# Voice preview sentences — cycled through on each click in UI
VOICE_PREVIEW_SENTENCES = [
    "Hello, this is a sample of my voice.",
    "The quick brown fox jumps over the lazy dog.",
    "I can read documents, articles, and research papers.",
    "Sometimes I wonder what it would be like to have a body.",
    "Breaking news: scientists discover that coffee is, in fact, essential.",
]


class VoiceRead(BaseModel):
    id: int
    slug: str
    name: str
    lang: str | None
    description: str | None


class ModelRead(BaseModel):
    id: int
    slug: str
    name: str
    description: str | None = None
    voices: list[VoiceRead] = []


@router.get("", response_model=List[ModelRead], dependencies=[Depends(authenticate)])
async def list_models(
    db: DbSession,
) -> List[ModelRead]:
    """Get all available TTS models with their voices (only active ones)."""
    models = (await db.exec(select(TTSModel).where(col(TTSModel.is_active).is_(True)))).all()
    return [
        ModelRead(
            id=cast(int, model.id),
            slug=model.slug,
            name=model.name,
            description=model.description,
            voices=[
                VoiceRead(
                    id=cast(int, voice.id),
                    slug=voice.slug,
                    name=voice.name,
                    lang=voice.lang,
                    description=voice.description,
                )
                for voice in model.voices
                if voice.is_active
            ],
        )
        for model in models
    ]


@router.get("/{model_slug}", response_model=ModelRead, dependencies=[Depends(authenticate)])
async def read_model(
    model: CurrentTTSModel,
) -> ModelRead:
    """Get a specific TTS model by slug (active voices only)."""
    return ModelRead(
        id=cast(int, model.id),
        slug=model.slug,
        name=model.name,
        description=model.description,
        voices=[
            VoiceRead(
                id=cast(int, voice.id),
                slug=voice.slug,
                name=voice.name,
                lang=voice.lang,
                description=voice.description,
            )
            for voice in model.voices
            if voice.is_active
        ],
    )


@router.get("/{model_slug}/voices", response_model=List[VoiceRead])
async def list_voices(
    model: CurrentTTSModel,
) -> List[VoiceRead]:
    """Get all active voices available for a specific model."""
    return [
        VoiceRead(
            id=cast(int, voice.id),
            slug=voice.slug,
            name=voice.name,
            lang=voice.lang,
            description=voice.description,
        )
        for voice in model.voices
        if voice.is_active
    ]


class VoicePreviewResponse(BaseModel):
    audio_url: str | None
    sentence: str
    sentence_idx: int
    error: str | None = None


@router.get("/{model_slug}/voices/{voice_slug}/preview", response_model=VoicePreviewResponse)
async def get_voice_preview(
    db: DbSession,
    redis: RedisClient,
    cache: AudioCache,
    user: AuthenticatedUser,
    model: CurrentTTSModel,
    voice: CurrentVoice,
    settings: Settings = Depends(get_settings),
    sentence_idx: int = Query(default=0, ge=0, lt=len(VOICE_PREVIEW_SENTENCES)),
) -> VoicePreviewResponse:
    """Get audio for a voice preview sentence. Synthesizes on-demand if not cached."""
    sentence = VOICE_PREVIEW_SENTENCES[sentence_idx]

    result = await synthesize_and_wait(
        db=db,
        redis=redis,
        cache=cache,
        user_id=user.id,
        text=sentence,
        model=model,
        voice=voice,
        billing_enabled=settings.billing_enabled,
        timeout_seconds=15.0,
        poll_interval=0.1,
    )

    return VoicePreviewResponse(
        audio_url=result.audio_url,
        sentence=sentence,
        sentence_idx=sentence_idx,
        error=getattr(result, "error", None),
    )

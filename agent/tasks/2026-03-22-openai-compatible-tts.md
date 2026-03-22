---
status: active
refs:
  - agent/handoffs/2026-03-22-openai-compatible-tts-adapter.md
  - agent/research/2026-03-22-openai-tts-ecosystem.md
---

# OpenAI-Compatible TTS Adapter

## Intent

Self-hosters are locked into either Kokoro (local GPU) or Inworld (proprietary API) for TTS. The OpenAI `/v1/audio/speech` API has become a de facto standard — vLLM-Omni (Qwen3-TTS), Kokoro-FastAPI, AllTalk, openedai-speech, Chatterbox TTS all implement it. Adding a generic adapter lets self-hosters plug in whatever TTS backend they want.

## Assumptions

- **Single endpoint is enough.** One configured OpenAI-compatible TTS endpoint. Multiple concurrent endpoints is future scope.
- **Billing is irrelevant for self-hosters.** `billing_enabled=false` makes usage checks a no-op. The existing `UsageType.premium_voice` fallback for non-kokoro models is fine.
- **Gateway dispatcher pattern.** API-based TTS uses `run_api_tts_dispatcher` (unlimited parallelism, no visibility tracking), same as Inworld.
- **`openai` SDK already available.** Added as optional dep in the extraction PR (#73).
- **`av` (PyAV) available for transcoding.** Already a dep — Kokoro uses it for PCM → OGG Opus.

## Approach

### 1. Adapter — `workers/adapters/openai_tts.py`

`OpenAITTSAdapter(SynthAdapter)` using `openai` SDK's `client.audio.speech.create()`. Retry logic following Inworld's pattern (exponential backoff on 429/500/503/504).

Voice parameter: `voice` string passed through from `Voice.parameters["voice"]`. No `speed` passthrough — frontend controls playback rate.

### 2. Audio format — detect and transcode

Request `response_format="opus"` from the API. On response:
- Check magic bytes for `OggS` header → pass through (already OGG Opus)
- Anything else → transcode to OGG Opus via `av` (PyAV)

This keeps the entire downstream pipeline unchanged (cache, audio endpoint `media_type="audio/ogg"`, frontend). Minimal quality loss when server natively supports OGG Opus (zero transcoding).

Duration estimation from OGG Opus byte size (same approach as Inworld adapter, ~14.5KB/sec).

### 3. Voice discovery — dynamic with env var fallback

On startup (gateway lifespan), try `GET {base_url}/audio/voices`. This is a community extension (vLLM-Omni, Kokoro-FastAPI have it; AllTalk, openedai-speech don't).

- If endpoint exists: use returned voice list
- If 404 / error: fall back to `OPENAI_TTS_VOICES` env var (comma-separated voice names, e.g. `alloy,echo,fable,nova,onyx,shimmer`)

Sync to DB on startup — create `TTSModel(slug="openai-tts")` with discovered/configured voices. Different from Inworld's `sync_inworld_voices` (which reads from a static JSON file we maintain) — this queries a live endpoint.

### 4. Config — `gateway/config.py`

```
openai_tts_base_url: str | None    # endpoint URL
openai_tts_api_key: str | None     # API key (some local servers don't need one)
openai_tts_model: str | None       # model name sent in the API request
openai_tts_voices: str | None      # comma-separated fallback voice names
```

All optional. Adapter activates when `openai_tts_base_url` is set.

### 5. Wiring — `gateway/__init__.py`

In lifespan, after the Inworld dispatcher block: if `openai_tts_base_url` is set, create adapter, sync voices, start dispatcher with slug `openai-tts`.

### 6. Env + docs

- Add commented-out section to `.env.selfhost.example`
- Update README
- Update knowledge files ([[tts-flow]], [[inworld-tts]] or new [[openai-tts]])

## Done When

- Self-hoster can set `OPENAI_TTS_BASE_URL` + `OPENAI_TTS_MODEL` and synthesize audio via any OpenAI-compatible TTS endpoint.
- Voice picker shows voices (auto-discovered or from env var fallback).
- Audio plays correctly in the frontend (OGG Opus, transcoded if needed).
- Tested with vLLM-Omni serving smallest Qwen3-TTS.

## Considered & Rejected

- **Hardcoded 6 OpenAI voices as seed data.** Rejected: too rigid, doesn't adapt to the actual TTS server's voice list. Env var fallback covers servers without a voices endpoint while keeping it configurable.
- **Speed passthrough.** Rejected: frontend already controls playback speed. Adding a server-side speed parameter adds complexity with no clear benefit.
- **Format-aware audio endpoint.** Rejected: transcoding to OGG Opus in the adapter is simpler than making the audio endpoint, cache, and frontend all format-aware. One transcode step vs. N downstream changes.

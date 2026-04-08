# Changelog

## Unreleased

* **Breaking:** Removed Inworld TTS integration — Inworld adapter, voices, and dispatcher deleted. Self-hosters using Inworld must switch to the OpenAI-compatible TTS adapter.
* Added Voice plan (€3/mo) — server-side Kokoro TTS without AI extraction.
* Added `/pricing` route (alias for `/subscription`).
* Removed Plus and Max subscription tiers (deactivated via migration).
* Word-level highlighting during Kokoro TTS playback. #78
* Fixed quota banner re-appearing after switching to a free/local voice.
* Fixed URL submission racing format loading, bypassing AI transform selector.
* Fixed arxiv title fetch with retry and reduced timeout.

## v0.2.0 — 2026-04-02

* **Breaking:** Default self-hosting no longer requires Stack Auth, ClickHouse, or TimescaleDB — runs 7 containers instead of 10. Existing selfhosters: `cp .env.selfhost.example .env.selfhost` and re-add your custom config. #80
* Multi-user mode available via `make self-host-auth` (adds Stack Auth + ClickHouse containers).

## v0.1.0 — 2026-04-02

First tagged release. Selfhosters can pin to this tag for a stable baseline.

* Added OpenAI-compatible TTS support — connect any `/v1/audio/speech` endpoint (vLLM-Omni, Kokoro-FastAPI, AllTalk, etc.). #74
* Added OpenAI-compatible AI extraction — use any vision model for PDF/image processing (vLLM, Ollama, OpenRouter). #73
* Added custom extraction prompts — configure per-user prompts for AI document extraction. #77
* Added bionic reading mode. #76
* Added image upload support for AI extraction. #75
* Fixed self-hosted schema migrations — now uses Alembic instead of `create_all`, preventing crashes on upgrade when new columns were added.
* Fixed batch mode being force-enabled for non-Gemini extraction processors.
* Fixed AI transform toggle showing when no processor is configured.
* Removed RunPod overflow system. #79
* Improved `.env.selfhost.example` with better organization and comments.

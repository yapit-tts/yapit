# Changelog

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

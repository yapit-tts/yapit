# Changelog

## v0.3.2 — 2026-07-20

* Security: updated python-multipart 0.0.22 → 0.0.32 (multipart upload parser), aiohttp, pillow, urllib3, idna, mako (backend) and react-router (frontend) — all Dependabot-flagged vulnerabilities.
* Gateway image now installs dependencies pinned and hash-checked from `uv.lock` instead of resolving them at build time — selfhost builds are reproducible and match tested versions.

## v0.3.1 — 2026-07-17

* Security: updated starlette 0.50.0 → 1.3.1 (via fastapi 0.139) — `Form()` size limits are now enforced for urlencoded request bodies, closing a memory-exhaustion DoS on upload endpoints (GHSA-82w8-qh3p-5jfq).
* Security: updated axios 1.13.5 → 1.18.0 — prototype-pollution and header-injection hardening (GHSA-898c-q2cr-xwhg).

## v0.3.0 — 2026-07-16

* **Breaking:** Removed Inworld TTS integration — Inworld adapter, voices, and dispatcher deleted. Self-hosters using Inworld must switch to the OpenAI-compatible TTS adapter.
* Added Voice plan (€3/mo) — server-side Kokoro TTS without AI extraction.
* Added `/pricing` route (alias for `/subscription`).
* Removed Plus and Max subscription tiers (deactivated via migration).
* Word-level highlighting during Kokoro TTS playback. #78
* Added HTML file upload support; URL fetching now uses a browser-like user agent and no longer rejects HTML error pages (e.g. soft 404s).
* Added per-request `extraction_prompt` override for AI extraction; fixed extraction progress polling when a custom prompt is set. #86
* Document sidebar now paginates with infinite scroll instead of loading all documents at once. #84
* Browser tab shows the document title on the playback page.
* Updated defuddle 0.15.0 → 0.19.1 — improved web content extraction (MathML reconstruction, table fixes, new site extractors) and a security fix sanitizing site-extractor HTML output (GHSA-jg4p-g6xj-4qmf).
* Fixed signed-in users being silently downgraded to their anonymous identity after a failed token refresh (zero-quota errors, lost reading position on mobile).
* Fixed Stripe webhooks 500ing on subscriptions of deleted (anonymized) accounts.
* Fixed missing whitespace between audio chunks in rendered documents. #88
* Fixed EPUB conversion of Springer academic citations and Obsidian footnotes. #85
* Fixed async extraction errors being masked by a generic message — real reasons (quota, validation) now reach the client.
* Fixed crash when synthesizing degenerate text that produces empty audio.
* Fixed file extension leaking into the document title when the filename is used as fallback.
* Fixed transient Stack Auth connection failures with a shared HTTP client and retries.
* Fixed progress bar dropping blocks that precede the first section heading.
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

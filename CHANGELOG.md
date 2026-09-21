# Changelog

## Unreleased

* Security: updated the XML parser behind defuddle's MathML-to-LaTeX conversion (`@xmldom/xmldom` 0.9.10 → 0.9.12), which now runs on every extracted page carrying math. The old version parsed and serialized malformed input in quadratic time and accepted names that bypassed its well-formedness checks (GHSA-6mj3-qw4j-hgrw, GHSA-g53g-w8rj-fmg7, GHSA-93r5-fhx6-vmg9 among them).
* Updated defuddle 0.19.3 → 0.19.4 — extracted web pages keep their punctuation where the site had it: no stray space before an em dash, a curly quote or an apostrophe, and none around subscripts, superscripts and inline code ("Popper's", "m³", "ViT-g₃₈₄"). Code blocks containing their own triple-backtick fences arrive intact instead of littered with backslashes, and content a site renders into a shadow root is now extracted instead of dropped.
* Fixed EPUBs showing small icons as full-size images: a book made with tex4ebook put a YouTube logo and a channel mark around every video link, each drawn at text size from a much larger file. An image the EPUB declares at 32 px or smaller now appears as its alt text, or not at all when it has none. EPUBs added before this fix keep the old rendering until added again.
* Placeholder alt text that conversion tools write on every image ("PIC", "image", "Image 3") is no longer read aloud, whatever the document's source.

## v0.4.6 — 2026-09-14

* Fixed free PDF extraction taking minutes on scanned books (Internet Archive and similar): text extraction was decoding every page image only to discard it. A 420-page scan went from 312 s to under a second, and while it ran, every other request to the server was stalled with it. #95
* The AI-extraction token estimate no longer runs when the account has no OCR tokens to begin with — it answers at once. The estimate itself had the same image-decoding cost on scanned pages (53 s for the same book, now 0.03 s); scanned pages are now recognised from the image's shape and size instead of its placement. #95
* Re-extracting a document with AI when some of its pages are already cached no longer re-extracts (and re-bills) the cached pages, and the up-front token check counts only the pages still to extract — a partly cached document is no longer refused for tokens it would not have spent. #96
* Playback now stops after three blocks in a row fail to synthesize, instead of silently skipping through the whole document (and saving a reading position the listener never reached); the synthesizer's own banner says what failed and offers the cloud voice. Blocks with nothing to voice (symbols, dashes, emoji) are skipped by the in-browser voice without counting as failures, as the server voices already did. #95
* Position saves are capped at one per two seconds while playing, with the resting position saved immediately on pause and on leaving the page. The save itself no longer loads the whole document to update one field. #95

## v0.4.5 — 2026-09-08

* Fixed every cache write taking about a minute once the audio cache grew to several GB — the size check on each commit summed entry sizes by reading through every stored blob. It now reads a small index instead; the same scan was also behind `/documents/prepare` slowing to 5–6 s. The index is built once when the gateway first starts on an existing cache file.

## v0.4.4 — 2026-09-08

* Security: updated the browser used to render JavaScript-heavy pages — Playwright 1.62.1 → 1.63.0, which bundles Chromium 153 instead of 151. This browser loads untrusted pages; Chromium 152 fixed a V8 type-confusion bug exploited in the wild (CVE-2026-85046) and a sandbox-escaping ANGLE use-after-free (CVE-2026-79282).
* Security: the SSRF proxy (smokescreen) that fronts every web-page fetch is now compiled with a supported Go toolchain (1.23 → 1.27) on Alpine 3.23. Go 1.23 left support in 2025-08, so the binary lacked a year of `net/http` and `crypto/tls` fixes, among them an HTTP/2 client hang (CVE-2026-33814) and TLS KeyUpdate flooding (CVE-2026-56862).
* Fixed a hidden browser tab with nothing playing reconnecting its WebSocket in a loop — hundreds of connect/disconnect pairs a day per idle tab. It now reconnects when the tab becomes visible or has something to send.
* Fixed over-long document titles, file names and URLs surfacing as an unhandled 500 — document-derived values are truncated, client-supplied ones rejected with a proper error.
* HTML uploaded from the browser now keeps its source URL, so root-relative links in the extracted content resolve and the document records where it came from.
* Metrics profile: the metrics writer emits an hourly `heartbeat` event while idle, so the health report can tell a quiet day from a dead metrics pipeline instead of guessing from log activity (which produced a false "pipeline down" every idle day).
* Updated defuddle 0.19.2 → 0.19.3 — footnote references no longer carry a stray space before the marker and footnote text keeps its trailing punctuation, so footnote-heavy articles read more cleanly. Ad, nav and ratings containers are stripped from more sites, as are "related stories" card blocks injected between paragraphs. Content is no longer dropped from sections whose class merely contains "logo" as a substring (e.g. "blogosphere").

## v0.4.3 — 2026-08-18

* Self-host on arm64 now actually gets the jemalloc allocator in the TTS and figure-detection workers — `LD_PRELOAD` pinned an x86-only library path, so arm machines silently fell back to glibc malloc (worse memory behavior on long-running workers).
* New `make self-host-smoke` — read-only health check of a running self-host stack: gateway, frontend proxy, and both workers. CI now boots the full self-host stack on an arm64 runner on every change, so Apple Silicon breakage is caught before it ships.

## v0.4.2 — 2026-08-18

* Fixed fresh self-host installs failing at gateway startup — database seeding collided with plan rows the migrations had already inserted, so a freshly migrated (empty) database hit a unique-constraint violation and the gateway never came up. Seeding now inserts only the missing plan tiers. #94
* Fixed `make self-host` on Apple Silicon / arm64 — the kokoro worker image failed to build (a dependency ships no arm64 wheel and the image lacked a C++ compiler to build it) and the gateway image downloaded an amd64-only pandoc package. #94

## v0.4.1 — 2026-08-18

* Security: updated the browser used to render JavaScript-heavy pages — Playwright 1.59.1 → 1.62.1, which bundles Chromium 151 instead of 147. This browser loads untrusted pages, so it picks up four Chromium majors of security fixes.
* Security: updated undici 7.28.0 → 7.29.0 (the HTTP client that fetches web pages) — Cache-Control parsing could disclose responses across users in shared caches, a blob-like request body could inject CRLF into headers, and the retry interceptor could desynchronize responses (GHSA-4cwx-7wf7-3272, GHSA-jr45-8vmc-qm54, GHSA-m8rv-5g2x-5cg5, GHSA-8xcm-r25x-g524, GHSA-v3r7-h72x-cjcm).
* Updated defuddle 0.19.1 → 0.19.2 — Wikipedia articles no longer lose every section after the first image row, X/Twitter extraction works again after their DOM changes, and extracted content now rejects `data:`/`blob:` URLs and keeps the `sandbox` attribute on iframes.
* Metrics recording now survives an unreachable metrics DB: events buffer and the writer retries with backoff instead of giving up permanently at startup. Only affects setups running the metrics profile.
* Plan page states storage limits in MB (the backend enforces bytes, not a document count) and no longer advertises a Voice/Basic document split that does not exist.
* Plan cards stack instead of squeezing into three columns until the viewport is wide enough for them, so feature lines stop wrapping several deep on tablets.

## v0.4.0 — 2026-08-02

* Fixed non-English Kokoro voices reading text with English pronunciation — each language now uses its own G2P pipeline; Japanese and Chinese (previously silent or spelling out "japanese letter"/"chinese letter") now work. #87
* Stale pre-fix audio for non-English voices is invalidated automatically (data migration changes their cache keys; old entries fall out of the LRU cache).
* Voice previews now speak the voice's own language instead of accented English.
* Word-level highlighting is now English-only: Spanish/French/Hindi/Italian/Portuguese voices previously showed highlighting (synced to the wrong-sounding audio); Kokoro's non-English pipelines don't produce word timestamps.
* Greatly reduced playback memory usage on long documents — audio stays Opus-encoded instead of being cached as decoded PCM, and the in-browser TTS worker now loads only when a browser voice is actually used.
* Billing consumer self-heals its Redis consumer group after Redis data loss; selfhost Redis now persists to a volume (append-only) so unacked billing events survive container recreation.
* Disabled ClickHouse self-telemetry logs — they grew unbounded (97GB on prod). Only affects auth-enabled setups.
* `GET /documents/{id}` now returns `created` (used by the yapit CLI to record when a source was captured).
* **Breaking (selfhost):** New required env var `RATELIMIT_ENABLED` — add `RATELIMIT_ENABLED=true` to your `.env.selfhost` (see `.env.selfhost.example`), or the gateway will fail to start.

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

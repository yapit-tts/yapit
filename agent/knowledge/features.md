# Features

User-facing capabilities.

## Document Input

- **Text/Markdown** — direct input or file upload (client-side read → `/text`)
- **URLs** — website extraction via defuddle (static-first, Playwright fallback for SPAs). arXiv URLs auto-detected, rewritten to PDF for free/AI toggle, titles fetched from arXiv Atom API
- **PDF** — free extraction (PyMuPDF) or AI extraction (Gemini, OpenAI-compatible). See [[document-processing]]
- **EPUB** — pandoc extraction with footnote conversion. See [[document-processing]]
- **Images** — AI extraction (Gemini, OpenAI-compatible). PNG, JPEG, WebP, HEIC/HEIF
- **Batch mode** — large PDFs (>100 pages) can use Gemini Batch API with status page
- **Custom extraction prompt** — per-user prompt override for AI extraction (Account → Advanced). Cache-keyed by prompt hash so different prompts don't collide

## Reading & Playback

- **Bionic reading mode** — bolds first ~50% of each word for visual fixation points (medium intensity). Toggle in settings
- **Document outliner** — right sidebar with collapsible H1/H2 sections. Collapse = hide + skip during playback. Per-document state persisted to localStorage
- **Footnotes** — split into own outliner section, hover preview on inline references (HoverCard)
- **Callouts** — Obsidian/GitHub/Bootstrap callout types mapped to color palette
- **Keyboard shortcuts** — hjkl/arrows (navigation), space (play/pause), +/- (volume), m (mute), o (outliner), r (back to reading), ? (help)
- **Command palette** — Cmd+K for document search and navigation
- **MediaSession / headphone controls** — OS media controls (lock screen, notification, dynamic island)
- **Smart scroll detach** — scroll during playback to detach, "Back to Reading" button to re-attach
- **Configurable content width** (narrow/medium/wide/full) and scroll position (top/center/bottom)
- **Section URL sharing** — outliner clicks update URL hash, hash anchors scroll on page load
- **Playback speed and volume** persisted in localStorage

## TTS

- **Kokoro.js** — browser-side TTS via Web Worker (WASM/WebGPU). Free, unlimited, no server needed
- **Kokoro server** — pull-based GPU workers for higher throughput
- **OpenAI-compatible TTS** — any `/v1/audio/speech` endpoint (Kokoro-FastAPI, vLLM-Omni, AllTalk, etc.). See [[tts-flow]]
- **Local TTS detection** — `useCanUseLocalTTS` disables browser TTS on mobile/no-WebGPU with explanatory UI
- **Voice picker search** — name + description match

## Sharing & Export

- **Document sharing** — share by link; viewers get clones preserving OCR work, use their own TTS quota
- **Markdown export** — `/md` and `/md-annotated` endpoints. Curl-friendly, nginx rewrite maps `/listen/{id}/md`
- **Compact embeds** — shared listen pages render as small text-only cards in Discord/Slack
- **Showcase documents** — pre-warmed cached content for new users

## Account & Billing

- **Self-hosting** — `make self-host` (no auth, no billing) or `make self-host-auth` (Stack Auth multi-user). See [[infrastructure]]
- **Dark mode** with multiple theme variants
- **Lifetime engagement stats** — per-voice listening time on account page (survives document deletion)
- **Usage breakdown** — per-voice and per-document on subscription page
- **Guest users** — anonymous HMAC sessions, 30-day TTL cleanup. See [[guest-users]]
- **Rate limiting** — per-IP per-endpoint + monthly caps on document creation. See [[security]]

## TTS Annotations

- `<yap-show>` — display only, silent in TTS (citations, refs)
- `<yap-speak>` — TTS only, hidden in display (math pronunciation)
- `<yap-cap>` — image captions (both display and TTS)

See [[markdown-parser-spec]] for detailed semantics.

# Features

User-facing capabilities. Links to task files (for simpler features) or dedicated knowledge files (for complex ones).

## Implemented

- [[2026-01-12-document-sharing]] — Share documents by link; viewers get clones to their library, preserving OCR work while using their own TTS quota
- [[2026-01-13-playwright-js-rendering]] — Automatic JS rendering for dynamic web pages (React, Vue, marked.js sites)
- [[2026-01-14-doclayout-yolo-figure-detection]] — Semantic figure detection in PDFs; handles vector graphics, groups multi-part figures, filters decorative elements
- [[markdown-parser-spec]] — TTS annotations (`yap-show`, `yap-speak`, `yap-cap`), footnotes, callouts
- [[2026-01-12-document-outliner]] — Right sidebar for navigating large documents; collapsible sections, filtered playback
- [[2026-01-28-smart-scroll-detach]] — "Back to Reading" button; scroll during playback to detach, click to re-attach
- [[rate-limiting]] — TTS rate limiting (300/min), concurrent extraction limits, storage-based document limits per tier
- Keyboard shortcuts — hjkl/arrows for navigation, space play/pause, volume/mute, `?` for reference popup. See [[frontend]] Keyboard & Media Controls section
- MediaSession / headphone controls — OS media controls (lock screen, notification, dynamic island) with document metadata, play/pause/skip
- Configurable content width (narrow/medium/wide/full) and scroll position (top/center/bottom) settings
- Playback speed and volume persisted in localStorage across sessions
- Voice picker bottom sheet on mobile (replaces overflowing popover)
- Tips page — local TTS troubleshooting, feature guides, keyboard/headphone docs
- AudioContext auto-resume — diagnostic logging + automatic resume on mobile suspension (app switch, phone call)
- URL catch-all routing — `yapit.md/<any-url>` extracts URL, redirects to home with pre-fill
- Gemini Batch Mode — large documents use Gemini Batch API with status page. See [[document-processing]]
- Markdown export — copy/download with yap tags stripped, annotated export option
- Showcase documents — pre-warmed cached content for new users without WebGPU
- Self-hosting — `make self-host` one-command setup

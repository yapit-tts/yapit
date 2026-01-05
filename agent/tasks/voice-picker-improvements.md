---
status: active
started: 2026-01-03
---

# Task: Voice Picker Improvements

## Issues

1. **Default to cloud Kokoro for subscribers** — if user has active plan, default to Cloud; if no plan, grey out Cloud with tooltip

2. **Inworld tab permissions** — entire Inworld tab should be disabled/greyed for free users (currently accessible)

3. **Info button for "Runs on" toggle** — explain Local (browser, slower on some devices) vs Cloud (server, faster, requires subscription). Similar to Inworld's Quality tooltip.

3. **Star button hitbox too small** — hard to tap on mobile

4. **Filter Kokoro local to English only** — browser WASM model only supports English, don't show other languages when Local selected

5. **Slow local inference hint** (nice-to-have) — if browser TTS takes too long, show hint with "Start trial" or "Export as MP3" options

## Files

- `frontend/src/components/voicePicker.tsx`

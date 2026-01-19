---
status: active
---

# Task: Inworld Temperature Setting

Add temperature as advanced toggle in voice picker for Inworld models.

## API Reference

- [Inworld Generating Audio docs](https://docs.inworld.ai/docs/tts/capabilities/generating-audio)
- Range: 0-2, default 1.1
- Lower = more deterministic, higher = more expressive
- Different temperature = different cache entry (already handled via voice `parameters` dict in variant hash)

## Implementation

- `yapit/workers/adapters/inworld.py` — pass temperature in request
- Frontend voice picker — advanced settings toggle with slider
- Store in voice parameters or user preferences

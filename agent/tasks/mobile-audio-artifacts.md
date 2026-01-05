---
status: active
started: 2026-01-03
---

# Task: Mobile Audio Artifacts at Block Boundaries

## Issue

Audio click/pop artifacts at block boundaries — only on mobile, not desktop.

## Background

Same issue previously occurred on desktop. Fixed by adding 10ms silence padding at end of each audio block (commit `936d740`). Theory was that silence helps the resampler handle block boundaries cleanly.

Sample rates in play:
- Kokoro: 24,000 Hz
- Inworld: 48,000 Hz
- Browser AudioContext: typically 44,100 Hz or 48,000 Hz (system-dependent)

So resampling happens. The silence padding helped desktop, but mobile still exhibits the artifacts — possibly different resampling behavior.

## Potential Fix to Explore

Gain fade at transitions — fade to 0 before stop, fade up after play (~10ms ramps via Web Audio `linearRampToValueAtTime`).

## Files

- `frontend/src/lib/audio.ts` — AudioPlayer class
- `frontend/src/pages/PlaybackPage.tsx` — playAudioBuffer function
- `yapit/gateway/api/v1/audio.py` — pcm_to_wav with silence padding

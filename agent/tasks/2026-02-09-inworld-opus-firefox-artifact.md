---
status: done
started: 2026-02-09
completed: 2026-02-09
---

# Task: Fix Inworld OGG_OPUS playback artifact in Firefox

## Intent

Migrating Inworld audio cache from MP3 to OGG_OPUS (matching Kokoro). Playback has an audible artifact at the start of every block in Firefox. Chromium browsers (Brave tested) play the same audio cleanly.

## The Artifact

User description: "it's like it is starting to play and I am hearing the start of the word or the sentence but it's like as if it then stutters or pauses or the quality drops for a split second." Present on EVERY block start, even when playing a single block in isolation after fresh page load.

## Confirmed Facts

- **Firefox-only.** Brave (Chromium) plays the same OGG_OPUS files with zero artifacts.
- **Inworld-only.** Server Kokoro (also OGG_OPUS, same encoder) plays clean in Firefox.
- **Audio data is clean.** Waveform analysis (PyAV decode) of Inworld's native OGG_OPUS, LINEAR16, and MP3 all show clean starts (peak < 0.002 in first 10ms). No transients. Script: `experiments/diagnose_inworld_audio.py`.
- **WAV header stripping is correct.** Inworld's LINEAR16 has a standard 44-byte RIFF header. Data chunk starts at byte 44 (verified by parsing chunk structure). First PCM samples are [2, 2, 2, 2...] (tiny DC offset, essentially silence).
- **Inworld OGG_OPUS is stereo.** Confirmed 2-channel, despite docs saying mono. This is a known gotcha (see [[inworld-tts]]).
- **Inworld LINEAR16 at 24kHz is mono.** Confirmed by WAV header parse and earlier chipmunk test.

## What Was Tested

| # | Backend | Frontend | Firefox Result |
|---|---------|----------|----------------|
| 1 | Inworld native OGG_OPUS (stereo 48kHz) | decode→WAV | Subtle artifact |
| 2 | Inworld native OGG_OPUS (stereo 48kHz) | direct OGG blob | Same artifact |
| 3 | Inworld native OGG_OPUS (stereo 24kHz) | decode→WAV | Same artifact |
| 4 | OGG_OPUS → decode → downmix mono → re-encode 48kHz | decode→WAV | Worse artifact |
| 5 | LINEAR16 24kHz mono → encode mono OGG_OPUS (same as Kokoro) | decode→WAV | Same artifact |
| 6 | #5 + 10ms silence prepended | decode→WAV | Same artifact |

All of the above play clean in Brave/Chromium.

**Kokoro (reference, works in Firefox):** mono 24kHz OGG_OPUS, 48kbps, PyAV/libopus encoder.

## What's Puzzling

Test #5 uses the EXACT same encoding pipeline as Kokoro (LINEAR16 mono → strip header → PyAV libopus → mono 24kHz 48kbps OGG_OPUS). Yet Kokoro plays clean in Firefox and Inworld doesn't. The only variable is the PCM content itself.

## Hypotheses NOT Confirmed

- ~~Stereo causing Firefox issue~~ — mono re-encode (#5) still has artifact
- ~~48kHz sample rate~~ — 24kHz (#5) still has artifact
- ~~Encoder pre-skip / warmup~~ — 10ms silence prepend (#6) didn't help
- ~~WAV header contamination~~ — header stripping verified correct
- ~~Double Opus compression quality loss~~ — single compression from LINEAR16 (#5) same issue

## Open Questions

1. **Is Kokoro truly clean in Firefox RIGHT NOW?** User confirmed earlier but has been iterating on Inworld since. Worth re-verifying with the current code.
2. **What about Kokoro's AudioBuffer vs Inworld's?** After `decodeAudioData()`, are the AudioBuffers different in some way? (sampleRate, numberOfChannels, length relative to expected)
3. **Firefox `decodeAudioData()` bug?** Maybe Firefox's implementation produces a glitch for specific PCM content characteristics. Could test by decoding in browser, inspecting the raw Float32Array samples for anomalies.
4. **Does the browser-side WAV conversion (`audioBufferToWav`) introduce the artifact?** Could test by playing the AudioBuffer directly through Web Audio API (AudioBufferSourceNode → destination) instead of converting to WAV.
5. **Cache contamination?** Are we sure we're not serving old cached audio from a different format? The variant hash doesn't include codec format.

## Recommended Next Steps

1. Verify Kokoro still clean in Firefox with current build
2. Add browser-side logging: after `decodeAudioData()`, log `audioBuffer.sampleRate`, `numberOfChannels`, `length`, and first 20 samples of channel 0
3. Compare the logged values between a Kokoro block and an Inworld block
4. Try playing AudioBuffer directly via Web Audio API (bypass WAV conversion) to isolate whether the artifact is in decode or in WAV playback

## Fallback Options

- **Switch Inworld back to MP3** — proven to work, slightly larger cache (~1.2x)
- **Accept Firefox quirk** — ship OGG_OPUS, document the Firefox issue, most users are on Chromium
- **Feature-detect Firefox + use MP3 for Firefox only** — complex, not worth it

## Resolution

The non-streaming endpoint (`POST /tts/v1/voice`) produced audio with higher startup energy in the first 10-20ms. Firefox was sensitive to this; Chromium masked it. Switching to the streaming endpoint (`POST /tts/v1/voice:stream`) with OGG_OPUS eliminated the artifact.

## Commits

- `1d69419` — feat: switch all TTS audio to OGG Opus, drop TTSModel codec columns

## Sources

**Knowledge files:**
- [[inworld-tts]] — stereo gotcha, API docs links
- [[tts-flow]] — full pipeline overview

**Key code files:**
- MUST READ: `yapit/workers/adapters/inworld.py` — current adapter (LINEAR16 → OGG_OPUS)
- MUST READ: `yapit/workers/adapters/kokoro.py` — reference working implementation
- MUST READ: `frontend/src/lib/audio.ts` — AudioPlayer, `loadRawAudio`, `audioBufferToWav`
- MUST READ: `frontend/src/hooks/usePlaybackEngine.ts` — where `decodeAudio` is wired
- MUST READ: `frontend/src/lib/serverSynthesizer.ts` — server synth decode path
- Reference: `frontend/src/lib/playbackEngine.ts` — block playback orchestration
- Reference: `experiments/diagnose_inworld_audio.py` — waveform analysis script

**Frontend state:**
- `decodeAudio` IS provided in usePlaybackEngine.ts (decode→WAV path active)
- `rawAudio` / `loadRawAudio` path exists but is NOT active (dead code from refactor attempt)
- `AudioBufferData` has both `buffer?` and `rawAudio?` fields

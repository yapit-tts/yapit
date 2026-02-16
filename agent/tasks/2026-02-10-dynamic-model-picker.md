---
status: active
started: 2026-02-10
---

# Task: Dynamic Model Picker for Custom/Self-Hosted Models

## Intent

Let self-hosters (and eventually yapit.md) add new TTS models without frontend code changes. Currently the voice picker hardcodes Kokoro and Inworld tabs with model-specific UI. A self-hoster who adds a new model to the DB + deploys a worker has no way to select it in the UI.

## Current State

- **Backend is model-agnostic.** Adding a model = seed DB rows + deploy a worker that pulls from `tts:queue:{slug}`. No gateway changes needed.
- **Frontend is hardcoded.** `ModelType` is a 4-literal union. Voice picker has two tabs with model-specific logic (Local/Cloud toggle, 1.5/Max toggle, hardcoded Kokoro voice array). Tier gating is per-model-family.

## Direction (Not Decided)

The general idea: keep hardcoded tabs for known models (business logic for yapit.md), auto-generate generic sections for unknown models from the `GET /v1/models` API. Self-hosters who add a model see it appear without touching frontend code.

No design decisions have been made. Key open questions:
- UI pattern for additional models (tabs, expandable sections, carousel?)
- How to handle model metadata the frontend needs (language grouping, descriptions)
- Whether Kokoro voices should move from hardcoded array to API-fetched (like Inworld)
- How model variants (Local/Cloud, quality tiers) should be expressed generically

## Sources

**Knowledge files:**
- [[tts-flow]] — synthesis pipeline, worker architecture
- [[frontend]] — React component hierarchy

**Key code files:**
- MUST READ: `frontend/src/components/voicePicker.tsx` — hardcoded model tabs, all the special casing
- MUST READ: `frontend/src/lib/voiceSelection.ts` — `ModelType` union, hardcoded Kokoro voices, localStorage utilities
- Reference: `yapit/gateway/api/v1/models.py` — generic model/voice API (already works for any model)
- Reference: `yapit/gateway/seed.py` — where models are defined
- Reference: `yapit/contracts.py:get_queue_name` — queue routing is `tts:queue:{model_slug}`, fully generic

---
status: done
started: 2026-02-01
---

# Task: Playback Engine Refactor

## Intent

Extract all mutable playback state from PlaybackPage.tsx into a standalone `createPlaybackEngine` factory function. Fixes cross-tab contamination, voice contamination, orphaned synthesis promises, and stale visual state — all caused by ~15 `useEffect` hooks triggering each other with no transactional boundaries.

## Assumptions

- No backend changes needed — WS messages already include `document_id`, `model_slug`, `voice_slug`
- Backend eviction race is harmless (subscriber notification path survives eviction)
- Multi-tab playback should work (filter by document_id, not restrict to one tab)

## Sources

**Knowledge files:**
- [[tts-flow]] — audio synthesis pipeline, caching, eviction
- [[frontend]] — React architecture, component hierarchy
- [[document-processing]] — block splitting, document structure

**Key code files:**
- MUST READ: `frontend/src/lib/playbackEngine.ts` — the new engine (875 lines)
- MUST READ: `frontend/src/hooks/usePlaybackEngine.ts` — React bridge (170 lines)
- MUST READ: `frontend/src/hooks/useTTSWebSocket.ts` — simplified WS hook (145 lines)
- MUST READ: `frontend/src/pages/PlaybackPage.tsx` — rewritten UI-only (679 lines)
- Reference: `frontend/src/lib/audio.ts` — AudioPlayer (added `setOnProgress`)
- Reference: `frontend/src/components/soundControl.tsx` — consumes snapshot via props

**Plan file:** `~/.claude/plans/hidden-snuggling-lantern.md`

## Done When

- [x] `playbackEngine.ts` — factory function with variant-keyed cache, event-driven synthesis, document_id filtering
- [x] `usePlaybackEngine.ts` — React bridge via useSyncExternalStore
- [x] `useTTSWebSocket.ts` — simplified to connection-only (376→145 lines)
- [x] `PlaybackPage.tsx` — rewritten to UI-only (1844→679 lines)
- [x] Type check passes
- [x] Vite build passes
- [x] `blockError` wired through engine snapshot
- [x] Fix unhandled promise rejections — replaced reject-based cancellation with resolve(null)
- [x] Fix voicePicker display bug (isKokoroModel function-as-boolean)
- [x] Fix Local/Cloud toggle persistence — removed auto-upgrade, default to Cloud
- [x] Manual testing: multi-tab, long doc, pause/resume, position persistence (voice switch verified)
- [x] Unit tests for `playbackEngine.ts` (step 6 from plan) — 39 tests

## Considered & Rejected

- **XState** — Overkill for ~4 states. Discriminated unions + switch is sufficient and zero-dependency.
- **Class-based engine** — Factory function avoids `this` binding issues, composes better, no friction with React conventions.
- **Hooks-only refactor** — Would replicate the same ref-based architecture. The problem is imperative state machine logic expressed as reactive effects.

## Discussion

- Agreed on discriminated unions for state modeling. Factory function (not hooks, not class) is the right container for the state machine — avoids `this` footguns, composes well, truly private state via closures. The `usePlaybackEngine` hook is just the React bridge.
- Confirmed backend contracts are clean — all WS messages include document_id, model_slug, voice_slug. No backend changes needed.
- Cancellation via `resolve(null)` instead of `reject(new Error(...))`. JS promises don't have a cancel concept; using reject for expected control flow (voice change, stop, timeout) caused unhandled rejection errors that were impossible to suppress cleanly — `.finally()` propagates rejections into new unhandled promise chains. `null` return means "cancelled, no audio" and the type system (`SynthesisResult = AudioBufferData | null`) enforces the check.
- Removed auto-upgrade (browser→cloud kokoro for subscribers). Default is now Cloud; quota banner reactively guides non-subscribers to Local or Upgrade. Simpler, no localStorage preference fighting.

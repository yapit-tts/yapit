---
status: active
started: 2026-02-10
---

# Task: Frontend Content, Playback & UX Issues — Research & Planning

Tracking task for parallel research into frontend-facing bugs and UX improvements. Agents research and plan only — no implementation.

## Intent

Investigate and plan fixes/features for all frontend content-rendering, playback, and UX issues identified in the TODO file. Each cluster gets a dedicated research agent. Results feed into implementation tasks.

## Clusters

### 1. Playback Bugs

- **Pause-then-play required** — Blocks show green/filled but won't play until pause→play or restart. Especially with Inworld. Suggests state machine or audio element issue.
- **Seek-to-start spinner bug** — Jumping back to start while playing shows infinite loading, but audio is cached. Pause→play resolves instantly.
- **Minimum blocks to start** — Currently >1; should evaluate setting to 1 since TTS is faster-than-realtime.

### 2. LaTeX/Rendering

- **Intermittent LaTeX unrendering** — Inline math shows raw LaTeX when block is highlighted/played. Not reliably reproducible, goes away on refresh.
- **Reload required for LaTeX** — Sometimes 1-2 reloads needed for all LaTeX to render. Possibly related to LaTeX within tables or other container elements.

### 3. Content & Navigation

- **Dead links refresh page** — `[link]()` with empty href causes navigation/refresh; should be inert but styled.
- **Footnotes in collapsed sections** — If last section is collapsed, footnotes unreachable. Should be section-independent.
- **Section URL sharing** — Outliner clicks should update URL hash so section links are shareable.

### 4. Markdown Export UX

- **Tag stripping toggle** — Export with yap tags stripped (clean markdown) vs preserved. Default: stripped. Research best UX patterns for this.

### 5. Back Buffer Sizing

- **Increase browser back buffer** — With Opus encoding, evaluate 16/32 blocks cached in-browser vs current.

## Sources

**Knowledge files:**
- [[frontend]] — Playback engine architecture, scroll handling, keyboard controls
- [[tts-flow]] — Synthesis pipeline, WebSocket protocol, cache architecture
- [[document-processing]] — Block structure, structured content format
- [[markdown-parser-spec]] — Yap tag semantics, footnotes, known limitations
- [[features]] — Existing feature list, outliner, smart scroll

**Key code files:**
- MUST READ: `frontend/src/lib/playbackEngine.ts` — Playback state machine
- MUST READ: `frontend/src/hooks/usePlaybackEngine.ts` — React bridge
- MUST READ: `frontend/src/components/structuredDocument.tsx` — Content rendering, LaTeX, block highlighting
- MUST READ: `frontend/src/hooks/useFilteredPlayback.ts` — Filtered playback indices
- MUST READ: `frontend/src/hooks/useOutliner.tsx` — Section state management
- Reference: `frontend/src/lib/serverSynthesizer.ts` — WebSocket synthesis path
- Reference: `frontend/src/lib/audio.ts` — AudioPlayer, HTMLAudioElement usage
- Reference: `frontend/src/pages/PlaybackPage.tsx` — Page-level playback orchestration

## Done When

Each cluster has:
- Root cause analysis (for bugs) or feasibility assessment (for features)
- Proposed solution with trade-offs
- Identified edge cases
- Estimated complexity

---
status: done
started: 2026-02-10
refs: [40b6503, 24182c0, 6a9bc28]
---

# Task: Frontend Content, Playback & UX Issues — Research & Planning

Tracking task for parallel research into frontend-facing bugs and UX improvements. Agents research and plan only — no implementation.

## Intent

Investigate and plan fixes/features for all frontend content-rendering, playback, and UX issues identified in the TODO file. Each cluster gets a dedicated research agent. Results feed into implementation tasks.

## Clusters

### 1. Playback Bugs

- **Pause-then-play required** — Blocks show green/filled but won't play until pause→play or restart. Especially with Inworld. Suggests state machine or audio element issue.
- **Seek-to-start spinner bug** — Jumping back to start while playing shows infinite loading, but audio is cached. Pause→play resolves instantly.
- ~~**Minimum blocks to start**~~ — ✅ Set to 1.

### 2. LaTeX/Rendering — ✅ Fixed (AST-based rendering refactor)

- ~~**Intermittent LaTeX unrendering**~~ — Fixed by AST-based rendering.
- ~~**Reload required for LaTeX**~~ — Fixed in same refactor.

### 3. Content & Navigation

- ~~**Dead links refresh page**~~ — ✅ Fixed in frontend refactor.
- ~~**Footnotes in collapsed sections**~~ — ✅ Fixed in frontend refactor.
- **Section URL sharing** — Outliner clicks should update URL hash so section links are shareable.

### 4. Markdown Export UX — ✅ Done

- ~~**Tag stripping toggle**~~ — Implemented.

### 5. Back Buffer Sizing — ✅ Done

- ~~**Increase browser back buffer**~~ — Set to 32 blocks.

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

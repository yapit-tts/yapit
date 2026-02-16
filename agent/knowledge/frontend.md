# Frontend

React SPA with Vite, shadcn/ui components, Tailwind CSS.

## Playback Engine

Standalone state machine that owns all playback logic. Extracted from PlaybackPage's tangled useEffects into a pure module with dependency injection.

**Key files:**
- `frontend/src/lib/playbackEngine.ts` — state machine (play, pause, skip, seek, prefetch, cache)
- `frontend/src/hooks/usePlaybackEngine.ts` — React bridge via `useSyncExternalStore`
- `frontend/src/lib/synthesizer.ts` — `Synthesizer` interface (browser vs server)
- `frontend/src/lib/browserSynthesizer.ts` — Kokoro.js Web Worker path
- `frontend/src/lib/serverSynthesizer.ts` — WebSocket path
- `frontend/src/lib/playbackEngine.test.ts` — unit tests (vitest)

**Architecture:** The engine exposes a `PlaybackEngine` interface (play/pause/stop/skip/seek/setVoice etc.) and a `subscribe`/`getSnapshot` pair for React integration. All I/O is injected via `PlaybackEngineDeps` (audio player, synthesizer), making the engine fully testable without DOM or network.

**Variant-keyed cache:** Audio is cached by `{blockIdx}:{model}:{voice}`. Changing voice invalidates entries. Changing document clears the entire cache (document identity is implicit).

**Cancellation pattern:** Pending synthesis promises resolve to `null` on voice change, stop, or document change. The `playBlock` loop checks for null and aborts, preventing orphaned audio from playing after the user moved on. See [[tts-flow]] for the server-side pipeline.

**Audio output:** `AudioPlayer` (`frontend/src/lib/audio.ts`) plays through `HTMLAudioElement` directly (no Web Audio routing). Speed control via `audioElement.playbackRate` + `preservesPitch`. Volume via `audioElement.volume` (read-only on iOS — hardware buttons only). An `AudioContext` exists separately for `decodeAudioData`/`createBuffer` in synthesizers but is NOT on the audio output path.

**Gotcha — HTMLAudioElement is required for pitch-preserving speed:** `AudioBufferSourceNode.playbackRate` changes speed AND pitch (chipmunk effect). Only `HTMLAudioElement` has `preservesPitch`. An intermediate SoundTouchJS approach was tried but had quality degradation above 1.6x. Don't go back to AudioBufferSourceNode for playback.

**Gotcha — do NOT route HTMLAudioElement through Web Audio (createMediaElementSource):** iOS Safari has a known bug (WebKit 211394) where `MediaElementAudioSourceNode` causes glitchy/choppy audio, especially with `playbackRate > 1`. Previous approach used this for GainNode volume control — caused audio to skip words, stutter on pause, and generally be unusable on mobile Safari. Volume slider is non-functional on iOS (audioElement.volume is read-only); this is acceptable since iOS users control volume via hardware buttons.

## Document Outliner

Right sidebar for navigating large documents. Shows section index from H1/H2 headings.

**Key features:**
- Collapse/expand sections — hides content in document view
- Skip sections — exclude from playback entirely (right-click/long-press)
- Filtered playback — progress bar scoped to expanded sections only
- Per-document section state (expanded/skipped sections) persisted to localStorage in PlaybackPage
- Outliner panel open/closed state persisted to cookie via `useOutliner`

**Key files:**
- `frontend/src/components/documentOutliner.tsx` — section tree with collapse/skip controls
- `frontend/src/hooks/useOutliner.tsx` — outliner panel toggle state
- `frontend/src/hooks/useFilteredPlayback.ts` — maps visual↔absolute block indices
- `frontend/src/lib/sectionIndex.ts` — builds section tree from structured content

**Design:** H1/H2 are "major headings" that create collapsible sections. H3+ are styled headings within sections but don't create nesting. Binary classification (major vs minor) is more robust than requiring consistent H1/H2/H3/H4 hierarchy across independently-processed pages.

**Gotcha — `data-audio-block-idx` dependency:**
Outliner navigation uses `scrollToBlock` → `findElementsByAudioIdx` which queries DOM for `[data-audio-block-idx="N"]`. If a block doesn't have this attribute, navigation silently fails (no scroll) but `currentBlock` still changes (buttons appear disabled). Don't remove this attribute to fix visual issues — find the actual root cause.

**Section headers are full audio blocks:** They're clickable for playback, hoverable for highlights, and get active styling. The collapse chevron is an *additional* affordance for expand/collapse, not a replacement for normal block behavior. See `structuredDocument.tsx` around line 1200.

**CSS alignment gotcha:** The highlight zone uses `padding-left` + `margin-left` (negative) to keep text position unchanged. If `blockBaseClass` has conflicting Tailwind margin (`-ml-1`), blocks with/without `data-audio-block-idx` will have different text alignment.

## Chrome DevTools MCP

Use Chrome DevTools MCP to visually verify changes, test user flows, and debug issues.

**Dev account:** `dev@example.com` / `dev-password-123` (from `scripts/create_user.py`)
- MCP browser has separate session - login required on first use
- Login: navigate to localhost:5173 → click Login → fill form → Sign In

**Key commands:**
- `take_screenshot` — see rendered UI
- `take_snapshot` — get DOM tree with element UIDs
- `click`, `fill`, `fill_form` — interact using UIDs from snapshot
- `list_console_messages` — check for JS errors/warnings
- `resize_page` — test responsive (375x812 for mobile, 1280x800 for desktop)

**Use for:**
- Visual verification after UI changes
- Console error checking (React errors, failed requests)
- Mobile/responsive layout testing
- User flow testing (login → input → playback → controls)
- Edge case verification without manual testing

**⚠️ CONTEXT WARNING — Large Snapshots:**
Action tools (click, fill, hover, etc.) automatically return full page snapshots. On complex documents this can be **30k+ tokens per interaction** — enough to consume most remaining context in one call.

**Before any DevTools interaction:**
1. **Create your own small test document** — don't use pre-existing documents in the sidebar, they're often huge (real webpages, long docs). Type a few lines of test content yourself.
2. **Sync task file first if context < 50%** — write current findings and next steps before the snapshot might consume remaining context
3. **Prefer screenshots for visual checks** — `take_screenshot` is much smaller than snapshots

Or even better: Use sub-agents that use devtools to debug for you!!!

**Exceptions:**
- If debugging a specific bug on a known large document, the large snapshot is unavoidable — just be handoff-ready first.
- For many bugs, screenshots lack precision — DevTools snapshots let you inspect element UIDs, exact positioning, and DOM structure. When you need that accuracy, the snapshot cost is worth it.

**If MCP won't connect:** Ask the user to close Chrome so MCP can launch a fresh instance.

**CSS debugging pattern:** When a style isn't applying, don't keep trying fixes at the same DOM level. Immediately trace upward:
```
element (Xpx) → parent (Ypx) → grandparent (Zpx) → ...
```
Find which ancestor is the constraint, fix there. Flex containers especially: children don't auto-stretch width in flex-row parents without `w-full`.

## CSS Theming

Check `frontend/src/index.css` for existing color variables before adding new colors. Prefer theme variables over hardcoded Tailwind classes (`text-emerald-600`) for consistency.

When adding UI, proactively refactor repeated color values into theme variables. If you see the same oklch/color used in multiple places, extract it.

**Gotcha — `text-primary` in dark mode:** Changes from green to gray between modes. Use `--accent-success` for text that should stay green in both modes.

## Scroll Handling

**Window scrolls, not the article:** The flex layout doesn't constrain article height, so `window` scrolls — listen there, not on container refs.

**Smooth scroll needs 800ms+ cooldown:** `scrollIntoView({ behavior: "smooth" })` fires scroll events for 300-500ms. Short timeouts cause false "user scroll" detection.

See [[2026-01-28-smart-scroll-detach]] for implementation details and additional gotchas (effect cascades, timer races).

## Keyboard & Media Controls

Keyboard shortcuts are registered in two places:
- **Global** (`frontend/src/components/ui/sidebar.tsx`) — sidebar toggle (`Ctrl+b` or bare `s`), works on any page
- **PlaybackPage** (`frontend/src/pages/PlaybackPage.tsx`) — playback controls: hjkl/arrows (skip/speed), space (play/pause), `+`/`-` (volume), `m` (mute), `o` (outliner), `r` (back to reading), `?` (help)

**MediaSession API** handles headphone/media key controls and OS media notifications (lock screen, dynamic island, notification shade).

Three layers in `PlaybackPage.tsx`:
1. **Action handlers** — play/pause/nexttrack/previoustrack/seekforward/seekbackward
2. **Metadata** — document title, "Yapit" artist, app icon artwork (`/icon-192.png`, `/icon-512.png`)
3. **Position state** — `setPositionState()` syncs progress bar + playback rate to OS controls

**AudioContext suspension recovery** (`usePlaybackEngine.ts`): Listens for `audioContext.onstatechange`. If the browser suspends the context while engine is active (mobile app switch, phone call), auto-attempts `resume()`. Diagnostic logging included.

**Gotcha — Firefox Android:** Exposes MediaSession API but doesn't wire it to Android's OS media controls (Fenix uses its own media component). API calls succeed silently but nothing shows. Known Mozilla bug since Firefox 82, unfixed as of 2026-02.

Wrap action handlers in try/catch per MDN recommendation since unsupported actions throw.

**Gotcha — stale closures in keyboard handlers:** The `handleKeyDown` useEffect has a stable dependency array for performance. Context-provided functions (like `sidebar.toggleSidebar`, `outliner.toggleOutliner`) change identity on re-renders, so they must be accessed via refs, not captured directly in the closure. Without refs, the handler captures the initial function and toggle only works one direction.

## Client-Side Hash Navigation

React Router client-side navigation doesn't trigger browser hash scroll. Pages that receive hash links (e.g., `/tips#billing`) need a `useEffect` watching `useLocation().hash` to scroll after mount. See `TipsPage.tsx` for the pattern.

## React Compiler

Enabled via `babel-plugin-react-compiler`. Auto-memoizes components/values — no need for manual `useMemo`/`useCallback` in most cases.

- ESLint rule `react-compiler/react-compiler` catches violations at lint time
- Opt out specific components with `"use no memo"` directive at function start
- Don't write to refs during render — move to `useEffect`

**Gotcha — shadcn/ui components:**
Some shadcn components assume Next.js SSR patterns. Example: sidebar cookie was write-only (SSR would read it server-side). In our SPA, we added client-side cookie reading on init.

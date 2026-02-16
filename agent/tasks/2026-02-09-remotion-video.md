---
status: active
started: 2026-02-09
---

# Task: Scaffold Remotion Video for Hackathon Demo

## Intent

Create a Remotion project to produce a ≤3 minute demo video for the Gemini 3 Hackathon submission. The video will combine screen recordings (recorded separately) with text overlays and transitions. Remotion is used as the composition layer — React-based, re-renderable, precise timing control.

## Context

READ THESE FIRST for product understanding:
- `docs/project-description.md` — hackathon submission text (what the product does, how it's built, challenges)
- `docs/architecture.new.md` — full architecture with mermaid diagrams (will be renamed to `docs/architecture.md`)

## Remotion Research

Explore the Remotion docs to understand:
1. Project setup (`npx create-video@latest` or manual)
2. `<Composition>`, `<Sequence>`, `useCurrentFrame()`, `useVideoConfig()`
3. **`<Video>` component** — embedding pre-recorded screen capture clips as assets
4. **`<Audio>` component** — embedding voiceover audio
5. **`<OffthreadVideo>`** — for better performance with multiple video files
6. Text overlays and animations (spring animations, opacity transitions)
7. **Rendering** — `npx remotion render` to mp4
8. Asset handling — where to put video/audio files, how to reference them

Docs: https://www.remotion.dev/docs/
Key pages to check: the-fundamentals, video, offthreadvideo, audio, sequence, spring, rendering, assets

## Video Structure

The video has 5-6 segments. Each segment will be a separate screen recording (~20-45s each). Between/over segments, there will be text overlays and possibly the architecture diagram.

**Key creative element:** Some narration segments will use Yapit itself to read the script — the presenter pastes narration text into the app's text input and plays it back. This is meta (the product demos itself) and memorable.

### Segment Plan

| # | Segment | ~Duration | Content | Narration |
|---|---------|-----------|---------|-----------|
| 1 | Hook | 10-15s | Text overlay introducing what Yapit does. Feature-focused, no personal story. | Possibly Yapit reading the hook text |
| 2 | Instant demo | 30s | "Attention Is All You Need" paper — cached, instant playback. Block highlighting, auto-scroll, outliner, voice picker. | Live voice or Yapit reading description |
| 3 | Live extraction | 40-50s | Paste new paper URL → prepare step (page count, cost) → GO → extraction progress bar → result. A paper with nice figures. | Explain Gemini pipeline while progress bar runs |
| 4 | The tags / markdown | 20s | Show the downloaded markdown — highlight `<yap-show>`, `<yap-speak>`, `<yap-cap>` tags. Or show a side-by-side of what displays vs what's spoken. | Explain the dual-channel system |
| 5 | Voices + browser TTS | 20s | Voice picker, switch voices, show WebGPU local synthesis. Maybe batch extraction. | Brief feature tour |
| 6 | Close | 10-15s | Text overlay: yapit.md, GitHub link, AGPL-3.0 | Yapit reading the closing line |

Total target: ~2:20-2:40 (buffer under 3:00)

## Remotion Project Structure

Scaffold a Remotion project (can live in a `video/` directory at repo root, or standalone). Create:

1. **Composition setup** — 1920x1080, 30fps, duration calculated from segments
2. **Segment components** — one per segment, each wrapping a `<Video>` component for the screen recording + any text overlays
3. **Placeholder structure** — use colored rectangles or test patterns where screen recordings will go (they don't exist yet). The structure should make it easy to swap in real recordings later.
4. **Text overlay components** — reusable component for text that fades in/out. Use the project's color scheme (cream background `#faf6f0`, green accents `#3a8a4d`, brown `#5c4a3a`).
5. **Transition component** — simple fade or cut between segments
6. **Render config** — set up so `npx remotion render` produces the final mp4

## Key Files for Color/Brand Reference

- `frontend/public/favicon.svg` — logo colors (green gradient `#5c4a3a` → `#4a6840` → `#3a8a4d`, sound wave green `#3a8a4d` / `#5aa86a`)
- `frontend/src/index.css` — CSS variables for the UI theme

## Done When

- [ ] Remotion project scaffolded and renders a placeholder video
- [ ] Each segment has a Composition with placeholder + timing
- [ ] Text overlay components work with project brand colors
- [ ] `npx remotion render` produces an mp4
- [ ] README or comments explain how to swap in real screen recordings
- [ ] Easy to adjust segment timing and re-render

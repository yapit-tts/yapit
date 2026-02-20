---
status: active
started: 2026-02-17
---

# Remotion Product Trailer

## Intent

Build product trailers for Yapit that make people want to try it. For social sharing: LinkedIn, YouTube, WhatsApp. Quality over speed, no deadline.

Two trailers, equally important:

1. **Product feel trailer (~30s)** — narrated by InWorld voices, shows the flow, breadth, and voice diversity. First impression, catches attention.
2. **PDF/technical trailer** — shows the real innovation: LaTeX/math/citations transformed into natural speech. Separate creative process.

## Creative Direction (Trailer 1)

### Narrated, not music-driven

Different English InWorld voices narrate over the product demo — each narrator line is itself a demonstration of voice quality. Background music may be added later as an energy layer if needed.

### Scene flow

1. **URL paste** — Craig: "Paste any link. An article. A paper. A book." Home page → paste URL → document loads. Sidebar closed from start. Use InWorld voices (not Kokoro) so synthesis is fast.

2. **Content breadth collage** — Ashley: "Listen to anything." Fanned card layout of 4-5 different content types (blog post, research paper, book, news article). Screenshots of the real app with different content, fanned like a hand of cards with spring-in animation. Shows yapit handles everything, not just one document type.

3. **Dark mode cycling** — Blake: "Any voice you want." + Hana: "Make it yours." Toggle through themes on the document. Visual click indicators or cursor. Playback speed bumped up so highlighting visibly jumps.

4. **Multilingual voice showcase** — 3-4 voices (curated, not exhaustive), then transition to a summary screen showing all available languages + total voice count (InWorld + Kokoro). Blake closer: "Try it now, on yapit.md!"

5. **End card** — yapit branding + CTA.

### Technical requirements

- InWorld voices only (not Kokoro) — both for narration and in-app playback
- Sidebar closed from scene 1
- Higher playback speed so highlighting moves noticeably in short time
- 1920x1080, 60fps target (Playwright capture at 30fps+ to avoid jank)
- App captures in light mode, dark modes for theme cycling scene

### Trailer 2: PDF/technical

- Shows actual PDF (e.g. "Attention Is All You Need") — raw two-column LaTeX with equations
- Demonstrates transformation: math → speakable, citations handled, figures detected
- Visual contrast between raw PDF and Yapit's clean rendering IS the hook
- Separate creative process — harder to make engaging, less time pressure

## Approach

**Playwright captures the real running app → Remotion composes captures into polished video.**

Pipeline proven across 6 sessions. `video/` is the self-contained trailer project with its own Makefile. Scripts (voice generation, capture) live in `video/`. Each scene is a separate Remotion composition (previewable in Remotion Studio). Edit voice lines, re-run, re-render.

## Assumptions

- The real app running locally is the source material (no mocks)
- Demo document: a blog post on yapit.md itself (user will write one; current placeholder is whatisintelligence.antikythera.org). User will re-record capture when the blog post exists.
- Each scene independently previewable in Remotion Studio
- InWorld voices only for the trailers
- Background music is optional / added last if needed

## Research

- [[remotion-trailer-research]] — Remotion capabilities, product trailer craft, feature inventory, code inventory, reference repos

## Done When

- **Trailer 1:** ~30-40s MP4, narrated by InWorld voices, shows: URL paste → content breadth collage → dark mode cycling → voice showcase (3-4 voices + language/voice summary) → end card. Sharp captures, accurate colors. Professional quality, makes someone want to try Yapit.
- **Trailer 2:** Shows PDF extraction + clean speech. Visually compelling raw PDF → Yapit transformation.
- Both: real app captures, on-brand visuals, modular Remotion code. Repeatable pipeline via Makefile.

## Considered & Rejected

- **Render app HTML inside Remotion** (sessions 1-2) — Tried inline-styled components, imported real components, iframes. All failed. Capture is strictly better.
- **Frame-by-frame Playwright screenshots** — Overengineered. `recordVideo` is sufficient.
- **Feature cards / text description overlays** — Generic, "AI slop" aesthetic.
- **Music-driven, no narration** (sessions 3-4) — Silence felt empty/low-energy. Evolved to different InWorld voices narrating, which doubles as voice quality demo.
- **"What if your papers could read themselves?"** — Too narrow, TTS isn't novel, feature-centric framing.
- **"Relatable" opening lines** — All cringe. Product speaks for itself.
- **Silent playback scene** (session 5) — With no synced audio, watching highlighting move in silence was awkward. Replaced with content breadth collage.
- **Research paper as demo content for trailer 1** — Too niche. Blog post shows broader appeal. Paper reserved for trailer 2.
- **Kokoro voices in trailer** — InWorld voices only.
- **9+ voice showcase** — Too long, gives impression of showing all voices when it's a fraction. 3-4 curated voices + summary is tighter.
- **Single-word voice clips** — "Escucha.", "Слушай." etc. — no character, no voice showcase value.

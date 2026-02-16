---
status: done
started: 2026-02-09
---

# Task: Gemini 3 Hackathon Submission Materials

## Intent

Prepare demo video and submission for Gemini 3 Hackathon. Deadline: Feb 9, 2026 @ 5:00 PM PST (2:00 AM Feb 10 CET).

## Submission Checklist

- [x] 200-word write-up — finalized in `docs/project-description.md` (elevator pitch section)
- [x] 200-char tagline — finalized
- [x] 3:2 icon — `frontend/public/icon-3x2.png`
- [x] Project description — `docs/project-description.md`
- [ ] Demo video (≤3 min) — see [[2026-02-09-remotion-video]]
- [ ] Public repo — cleanup in progress
- [ ] Public demo link — yapit.md (already live)
- [ ] All teammates accepted on Devpost

## Video Script (≤3 minutes)

**Key creative element:** Yapit reads parts of the script itself — paste narration text into the text input, play it back. The product demos itself while narrating. Memorable and meta.

**Style:** Feature-focused. No personal story in the hook. Show the product working. Explain the Gemini integration concretely.

### Segment 1 — Hook (10-15s)

Text overlay or Yapit reading:

"Yapit turns documents into natural audio. Paste a research paper — math displays but stays silent, figures show with extracted images, citations become prose. The extraction is what makes it work."

### Segment 2 — Instant Demo: Attention Paper (30s)

Screen recording: Open "Attention Is All You Need" on yapit.md (cached, instant).

Show:
- Click document → loads instantly
- Hit play → block highlighting, auto-scroll
- Clean headings, YOLO-extracted figures, LaTeX rendered but silent
- Outliner: collapse/skip sections
- Voice picker: switch between voices, show multiple languages
- Speed control

Script (voice or Yapit reading):
"This is 'Attention Is All You Need' — fully extracted and cached. Every figure detected by YOLO, every equation rendered with KaTeX. The audio skips the math notation and reads natural descriptions instead. You can navigate by section, skip what you don't need, pick any voice."

### Segment 3 — Live Extraction (40-50s)

Screen recording: Paste a new paper URL (Google research paper or paper with nice figures).

Show:
- Prepare step: page count, cost estimate displayed
- Click GO with AI Transform on
- Extraction progress bar — pages completing one by one
- While waiting: briefly show the architecture diagram or extraction prompt
- Extraction completes → document renders with figures, formatted text

Script:
"Now a fresh paper — not cached. Each page goes to Gemini 3 Flash as an image, in parallel. YOLO runs figure detection — not just embedded rasters, but vector graphics and multi-part diagrams. Gemini produces structured markdown with semantic tags: yap-show for display-only content like equations, yap-speak for spoken descriptions, yap-cap for image captions. Results are cached per page — if you re-extract later, only changed pages reprocess."

### Segment 4 — The Tags (20s)

Screen recording: Download the markdown, open in editor. Highlight `<yap-show>`, `<yap-speak>`, `<yap-cap>` tags.

Or: side-by-side of what displays vs what's spoken.

Script:
"Here's what Gemini actually outputs. The LaTeX is wrapped in yap-show — it renders visually but the audio gets this natural description instead. Figure captions in yap-cap are both displayed and spoken. When there's no caption, Gemini generates alt-text."

### Segment 5 — More Features (20s)

Screen recording: Quick feature tour.

Options (pick 2-3):
- Browser-local Kokoro TTS via WebGPU (free, private, no server)
- Batch extraction (kick off a large document, show 50% cost savings)
- Keyboard shortcuts, media controls
- Document sharing

Script:
"Kokoro runs entirely in your browser via WebGPU — free, private, no server needed. For large documents, batch mode passes on Gemini's 50% cost reduction. Keyboard shortcuts, media controls, document sharing — it's a full platform."

### Segment 6 — Close (10-15s)

Text overlay or Yapit reading: yapit.md, GitHub link, AGPL-3.0.

"Open source. Try it at yapit.md."

### Total: ~2:20-2:40

---

## Recording Plan

1. Record each segment as separate screen capture (SimpleScreenRecorder or similar)
2. Narration options per segment:
   - **Yapit reading:** Paste script text into Yapit, play back with a good voice. Record the screen showing this.
   - **Live voice:** Record voiceover separately with USB mic
   - **Mix:** Some segments Yapit, some live voice
3. Compose in Remotion — see [[2026-02-09-remotion-video]]
4. Re-render as needed when adjusting timing/text

## Done When

- [ ] Video script finalized
- [ ] Screen recordings captured for all segments
- [ ] Video composed and rendered (≤3 min)
- [ ] Submitted on Devpost before deadline

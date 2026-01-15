---
status: done
started: 2025-01-08
completed: 2026-01-15
pr: https://github.com/yapit-tts/yapit/pull/56
---

# Task: Gemini 3 Flash Integration - Exploration & Planning

Parent: [[llm-preprocessing-prompt]]

## Intent

Evaluate Gemini 3 Flash as a replacement for Mistral OCR. Gemini is potentially cheaper ($1.40-1.70/1000 pages vs $2/1000) while providing transformation instead of just extraction.

This subtask focuses on:
1. **Empirical benchmarking** — Does low resolution suffice? Where does it fail?
2. **Integration architecture** — How does Gemini fit into the existing processor interface?
3. **Configuration decisions** — What user controls (if any) make sense?

Output: Documented findings + recommendations for implementation.

## Sources

**MUST READ:**
- `experiments/gemini-flash-doc-transform/process_doc.py` — prod-like pipeline (resolution comparison, stitching)
- `experiments/gemini-flash-doc-transform/process_pdf.py` — prompt tuning script (other agent)
- `yapit/gateway/processors/document/mistral.py` — current OCR interface to match
- `yapit/gateway/processors/document/base.py` — BaseDocumentProcessor interface

**Reference:**
- [Gemini Document Processing](https://ai.google.dev/gemini-api/docs/document-processing)
- [Gemini Media Resolution](https://ai.google.dev/gemini-api/docs/media-resolution)
- [Gemini Pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Gemini Rate Limits](https://ai.google.dev/gemini-api/docs/rate-limits) — Batch API: 3M enqueued tokens (Tier 1); Non-batch API: community-reported ~1k RPM / 1M tokens/min for paid tier (unverified, check AI Studio for actual limits)

## Questions to Answer

### 1. Resolution Quality
- Is low resolution sufficient for most documents?
- Where does low fail (complex math, tiny text, dense tables)?
- Is medium the sweet spot, or is high ever necessary?

### 2. Page Handling
- Current: page-by-page processing
- Problem: sentences/paragraphs can split across pages
- Options:
  - Ignore (most pages are self-contained)
  - Prompt: "if text appears cut off, indicate it continues..."
  - Post-processing: stitch fragments
  - Batch multiple pages in one call (token limit?)

### 3. User Configuration
- Should resolution be user-configurable?
- Presets by document type (arXiv, textbook, general)?
- Or: auto-detect complexity?

### 4. Replace vs Augment Mistral
- If Gemini quality ≥ Mistral: full replacement
- If tradeoffs exist: offer both (adds complexity)

## Experiment Plan

### Phase 1: Resolution Comparison
Test documents:
- [x] arXiv paper with equations (1706.03762 - "Attention Is All You Need")
- [ ] Dense textbook page
- [ ] Scanned document (real-world quality)
- [ ] Complex tables/figures

Compare: low vs medium vs high
Metrics: readability, math accuracy, missing text

### Phase 2: Page Boundary Handling
- Find documents with cross-page sentences
- Test current page-by-page approach
- Experiment with context prompting

### Phase 3: Integration Design
- Map Gemini to `BaseDocumentProcessor` interface
- Determine config options
- Error handling strategy

## Preliminary Findings (v1 prompt, "Attention Is All You Need" paper)

**Cost comparison (15 pages):**
- Low: 47,753 tokens, $0.036
- Medium: 54,047 tokens, $0.038 (+6% vs low)
- High: 58,173 tokens, $0.043 (+12% vs medium)

**Quality comparison (extraction prompt v1):**
- **Medium is the sweet spot** — better symbol rendering than both low AND high
- Low: `†`, `‡` as unicode; missing `\mathbf{}` on vectors; awkward figure handling (text broken up)
- Medium: proper LaTeX (`$\dagger$`, `$\ddagger$`); consistent math; clean text flow
- High: unexpectedly regresses — uses unicode symbols like low; different separator choices

**Key insight:** Resolution doesn't monotonically improve quality. Medium appears optimal for this document type.

## Figure Extraction Design

### User Intent
When reading academic papers via TTS, users want to see figures alongside the audio without opening the original PDF in a separate tab. The goal is a self-contained reading experience where the extracted content is complete enough that you don't need to reference the source.

### Alternatives Considered

**Option 1: Gemini describes figures in text**
- Rejected: Doesn't solve the use case. User wants to *see* the figure, not hear a description.
- Note: Could be a separate accessibility feature (toggle for figure descriptions for visually impaired users).

**Option 2: Mistral OCR for image extraction**
- Has `include_image_base64` that returns cropped figures
- Rejected: Cropping quality varies, we want to move away from Mistral dependency anyway

**Option 3: Render full PDF pages as images**
- Show whole page screenshots synced to playback position
- Rejected: Doesn't fit UI. We produce styled markdown, not embedded PDFs.

**Option 4: PyMuPDF self-extraction** ← chosen
- Extract embedded images directly from PDF structure
- Works well for native PDFs (arXiv, LaTeX-compiled)
- No external API dependency, very fast (pure file parsing)
- For scanned PDFs: can detect and skip figure extraction (text still works via Gemini)

### Scanned vs Native PDFs
- **Native (arXiv, LaTeX):** Multiple discrete images in PDF structure → extract cleanly
- **Scanned:** 1-2 large images covering entire page → detected via page coverage heuristic (>80% = scanned)
- For scanned: skip figure extraction, still process text via Gemini

### Flow
1. **PyMuPDF extracts images** from each page first (fast, no API call)
2. **Count images per page** before calling Gemini
3. **Prompt includes image count:** "This page has N figures. Place exactly N `{{{IMAGE}}}` markers where figures appear."
4. **Substitute placeholders** with extracted images in order
5. **Handle mismatches:** More placeholders than images → remove excess. More images than placeholders → append at page end.

### Implementation Details
- **Placeholder format:** `{{{IMAGE}}}` — distinctive (won't appear in real content), easy regex, LLM can output naturally
- **Storage:** Base64 data URLs in markdown/structured_content. No separate file management.
- **Size cap:** None artificial. Document upload limit (50MB) is the real constraint. No reason to compress figures that browsers can handle fine.

### Parallelization
- Sequential processing is slow (~10-15s/page)
- **Approach:** Batch 10-20 pages with `asyncio.gather()`
- Rate limits (unverified community numbers): ~1k RPM, ~1M tokens/min for paid tier
- Tested: 15 pages in ~31-36s (vs ~150s sequential) — significant speedup

### Known Limitations & TODOs

**Vector graphics not extracted:**
- PyMuPDF's `get_images()` only finds embedded raster images
- Vector graphics (drawn with PDF commands) are not extracted
- Example: Attention visualizations in appendix of "Attention Is All You Need" are vectors
- Gemini sees them and places `{{{IMAGE}}}` but no image to substitute
- Current behavior: excess placeholders are removed (acceptable degradation)
- Future option: render page as image if Gemini sees more images than extracted

**Side-by-side figures:**
- Some figures are visually side-by-side (e.g., "Scaled Dot-Product Attention" + "Multi-Head Attention")
- PyMuPDF correctly extracts as 2 separate images
- Gemini correctly places 2 `{{{IMAGE}}}` markers
- TODO: Prompt could instruct Gemini to indicate side-by-side layout (e.g., `{{{IMAGE:left}}}` `{{{IMAGE:right}}}`)
- TODO: Frontend/transformer would need to handle side-by-side rendering
- Low priority: works fine as sequential images for now

## TODO: Automated Comparison Workflow

We can automate quality assessment to some degree:
1. **Diff-based:** Compare outputs across resolutions, flag meaningful differences
2. **Heuristic scoring:** Count LaTeX symbols vs unicode, check for text fragmentation
3. **Human review:** User judges accuracy against original, TTS-friendliness

Next step: Build comparison tooling once prompts stabilize.

## Gotchas

- Resolution doesn't monotonically improve quality — high can be worse than medium
- Output format depends heavily on prompt, not just resolution
- Page stitching heuristic: join with space if prev ends without punctuation + next starts lowercase

## Resolution Cost Analysis

**v2 prompt results (15 pages, 3 images):**
| Resolution | Tokens | Cost | vs Low | vs Medium |
|------------|--------|------|--------|-----------|
| Low | 63,116 | $0.036 | — | -5% |
| Medium | 56,742 | $0.038 | +6% | — |
| High | 73,148 | $0.042 | +17% | +11% |

**Decision:** High is only ~17% more than low. Quality difference matters more than marginal cost savings. Will validate with more documents, but likely default to medium or high.

## Prompt Architecture

**Key insight:** Separate base prompt from injected additions.

**Base prompt template** (user-copyable):
- Extraction/transformation rules
- Formatting instructions
- User can copy this to use with their own AI models

**Injected additions** (not user-facing):
- Image count per page: "This page has N figures..."
- Post-processing specific (image placeholders)
- Added AFTER base prompt at runtime

This separation makes sense because:
- Users can't have their AI generate base64 images — that's our post-processing
- User template should be standalone and useful outside yapit

## Next Phases

### Phase 2: Extended Benchmarking (parallel with prompt tuning)
- Collect 3-5 diverse test documents
- Run all 3 resolutions on each
- Compare: text quality differences, not just cost/tokens
- Validate whether high resolution is worth default

### Phase 3: Yapit Integration
- Replace Mistral processor with Gemini
- Refactor document endpoint
- End-to-end testing in real UI

## Integration Design Questions

### Parallelization / Rate Limiting
- **Goal:** Global request scheduler for Gemini API
- **Behavior:** Parallelize to max capacity
  - Single user, 30-page doc → send 30 requests
  - 20 concurrent users → budget requests across all
- **Questions:**
  - What are our actual rate limits? (need to verify in AI Studio)
  - How do limits scale as usage grows?
  - Batch API toggle for background processing? (higher limits)

### Frontend Considerations
- Quick POC first, don't rush
- UI for batch vs priority toggle?
- Progress indicator for multi-page processing

### Data URL / Export Handling
**Problem:** Frontend has download/copy markdown functionality. Naively including base64 data URLs is bad UX:
- Overwhelms many applications (huge text blobs)
- Wrong for >80% of export use cases

**Options:**
1. **Frontend filter:** Strip data URLs on export → replace with nothing or placeholder text
2. **Separate image storage:** Save extracted images under our domain (e.g., `yapit.app/images/{doc-id}/{img-index}.png`), use normal URLs in markdown
3. ?

Option 2 is cleaner long-term but adds storage/serving complexity. Option 1 is simpler but loses images on export.

**Hybrid:** Store images separately, use real URLs in markdown. Data URLs only as fallback/initial implementation.

### Backend Integration
- Replace Mistral processor or add alongside?
- Same interface as current OCR flow
- Resolution as config option (or always high?)

## Handoff

**Status:** Pipeline built with image extraction + parallel processing. v2 prompt tested on all resolutions. Ready for integration planning.

**Suggested task invocations:**

**1. Prompt tuning (other agent, ongoing):**
```
/task @agent/tasks/llm-preprocessing-prompt.md Continue prompt tuning. Focus on: inline math rendering, inline references ([1], [2], etc.), edge cases. Research best practices.
```

**2. Extended benchmarking (can run when user has test docs):**
```
/task @agent/tasks/gemini-integration-exploration.md Run resolution comparison on new test documents. Compare text quality, not just cost. User will provide PDFs.
```

**3. Yapit integration (Phase 3, new task file):**
```
/task Create new task: Gemini processor integration into yapit. Review: document endpoint, Mistral processor code, BaseDocumentProcessor interface. Plan: replace Mistral, parallelization strategy, rate limiting, frontend POC.
```

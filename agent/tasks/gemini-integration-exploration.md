---
status: active
started: 2025-01-08
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

## Handoff

**Status:** Pipeline built, preliminary resolution data gathered. Waiting for prompt tuning to stabilize before deeper testing.

**Next steps:**
1. Wait for prompt tuning agent to produce TTS-friendly prompt
2. Re-run resolution comparison with TTS prompt
3. Add more document types (scanned, tables, textbooks) as encountered
4. Design backend integration once quality findings are solid

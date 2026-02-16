---
status: active
started: 2026-02-12
---

# Task: Improve PyMuPDF Free PDF Extraction Quality

## Intent

PyMuPDF `get_text()` is 17-41x faster than MarkItDown but produces worse output on PDFs with complex figures. The "Attention Is All You Need" paper (1706.03762v7) is a clear failure case: text labels from attention heatmap figures are extracted as body text, producing repeated garbage like "The Law will never be perfect, but its application should be just" (the sentence used in the attention visualizations).

Goal: improve output quality without significantly sacrificing speed. This is an iteration task — build a benchmark tool, then iterate rapidly: try an approach, measure, compare, adjust.

## Problem Analysis

`doc[idx].get_text()` (defaults to `get_text("text")`) extracts ALL text on a page indiscriminately — body text, figure labels, annotations, watermarks, rotated sidebar text. It has no concept of reading order or text role.

Papers with embedded text in figures are the worst case. The attention paper has figures where input sentences are printed along both axes of attention matrix heatmaps — PyMuPDF extracts all those labels as if they were body text.

MarkItDown (via pdfminer) had better layout analysis that could partly distinguish body text from figure annotations, though it was still far from perfect.

## Starting Points

These are ideas to explore, not a plan to execute sequentially. Try things, measure, follow the gradient.

- **`get_text("blocks")`** — returns blocks with bounding boxes + type (text vs image). Filter blocks overlapping image regions, dedup repeated blocks (figure axis labels).
- **`get_text("dict")`** — structured data with font name/size/color/position per span. Filter by unusual font sizes, rotated text, text inside image bounding boxes.
- **Post-processing heuristics** — dedup lines appearing >N times per page, strip rotated arXiv sidebar text, remove very short repeated fragments.
- **Combination** — e.g. use `get_text("blocks")` for the basic extraction but filter with image region overlap detection.

### `pymupdf4llm`

Previously measured at 2x slower than MarkItDown (67s vs 32s on 714-page textbook). We didn't deeply investigate whether the layout analysis bottleneck can be selectively disabled. Worth a quick check, but strong preference for raw PyMuPDF + heuristics over pulling in another large dependency if we can get comparable results.

## Methodology

1. **Build benchmark tool first** — measures extraction time + lets you compare outputs side by side. Use an LLM sub-agent to assess quality (readability, garbage detection, completeness) or compare outputs directly.
2. **Iterate** — try an approach, run the benchmark, see what improved and what regressed, adjust. Quick feedback loops. This includes improving the tooling itself — write scripts, make comparison easier, automate the feedback loop. Don't plan 5 approaches upfront and implement them all — try one, measure, decide next step based on results.

## Test Corpus

There is no existing baseline. The agent needs to establish how current extraction performs across the corpus, then improve from there.

**Local books** — `/home/max/Documents/books/` contains a variety of PDFs (textbooks, etc.).

**Fetchable papers** (agent can download from arXiv or direct URLs):
- "Attention Is All You Need" (1706.03762v7) — the known failure case: output contains only repeated figure label text, actual paper content (abstract, sections, etc.) is completely missing
- Other well-known papers with figures, tables, multi-column layouts — agent picks a diverse set

The corpus should cover: simple text-only, two-column academic, figure-heavy, math-heavy, very long (speed benchmark).

## Constraints

- Speed is critical — free extraction must remain fast. <1s for typical PDFs, <5s acceptable for very large ones.
- This is the FREE path — perfection isn't expected. AI transform exists for users who need high fidelity.
- Changes are isolated to `yapit/gateway/document/processors/pdf.py`

## Sources

**Key code files:**
- MUST READ: `yapit/gateway/document/processors/pdf.py` — current implementation (simple `get_text()`)
- Reference: `yapit/gateway/document/processing.py` — ProcessorConfig, process_with_billing interface
- Reference: `[[2026-02-11-remove-markitdown-processor-refactor]]` — context on why MarkItDown was removed, pymupdf4llm rejection rationale

## Done When

- Benchmark tool exists with curated PDF corpus
- At least one approach measurably improves output quality on figure-heavy PDFs
- No significant speed regression (<2x slowdown on baseline PDFs)
- Simple text-only PDFs are not degraded

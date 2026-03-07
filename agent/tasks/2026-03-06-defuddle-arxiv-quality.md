---
status: active
refs:
  - "[[2026-03-05-defuddle-website-extraction]]"
  - "[[2026-03-06-defuddle-arxiv-issues]]"
  - "[[2026-03-06-defuddle-arxiv-quality-audit]]"
---

# Defuddle arXiv quality: upstream issues + our pipeline fixes

## Intent

Systematic quality improvement for defuddle's arXiv output. Two tracks:

1. **Upstream:** File well-scoped issues with minimal repros for defuddle bugs
2. **Our pipeline:** Post-processing and transformer fixes for things that are our responsibility

This task covers the quality side. The parent task [[2026-03-05-defuddle-website-extraction]] covers the infrastructure (sidecar timeout, concurrency, routing, markxiv removal).

## Research

- [[2026-03-06-defuddle-arxiv-quality-audit]] — comprehensive paper-by-paper audit of all 7 outputs. Issue catalog, severity matrix, owner assignments, concrete examples.
- [[2026-03-06-defuddle-arxiv-issues]] — root cause analysis for equation tables, `<sup>` leakage, nav TOC, double captions. Includes minimal repro HTML.

## Assumptions

- Defuddle upstream (kepano) is responsive and will fix well-reported bugs. If not, we may need sidecar-side pre-processing.
- Title prepend from defuddle metadata is the right short-term fix — we don't need to wait for upstream to include it in content.
- Citation bracket noise and footnotemark text can be stripped in post-processing without losing meaningful content.
- `<sup>`/`<sub>` rendering is our responsibility — defuddle correctly keeps them as HTML, our transformer needs to handle them.

## Done when

- [ ] Upstream issue filed: equation tables (critical — covers performance hang + equation rendering)
- [ ] Upstream issue filed: missing title in content
- [ ] Upstream issue filed: empty citation brackets
- [ ] Upstream issue filed: doubled `<sup>` + footnotemark text leak
- [ ] Upstream issue filed: cross-reference numbers lost
- [ ] Our pipeline: title prepended from defuddle metadata
- [ ] Our pipeline: `<sup>`/`<sub>` handled in transformer.py (display + TTS)

## Considered & rejected

- **Filing a single umbrella "arXiv support" issue** — too broad, makes it hard for upstream to triage and track. Individual focused issues with minimal repros are more actionable.
- **Post-processing citation brackets / footnotemark text in our pipeline** — these are symptoms of upstream bugs (broken citation handling, broken footnote mark handling). If defuddle fixes the root causes, the symptoms disappear. Don't build workarounds for things upstream should fix.
- **Sidecar-side pre-processing for equation tables** — at that point just fork. But upstream is responsive, file the issue first.
- **Stripping all `<sup>` content** — wrong approach. Superscripts carry meaningful content (exponents, ordinals) outside of footnote marks. We need to render them, not strip them.

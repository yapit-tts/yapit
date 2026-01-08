---
status: active
type: tracking
started: 2025-01-06
---

# Gemini Document Processing Integration

Replace Mistral OCR with Gemini 3 Flash for document processing. Cheaper AND provides transformation instead of just extraction.

## Subtasks

- [[gemini-prompt-engineering]] — Research prompting, draft TTS-optimized extraction prompt
- [[gemini-resolution-benchmarking]] — Benchmark resolutions, integration planning, frontend ideas

## Two paths forward

1. **Integrated Gemini** — Replace Mistral OCR. Convenient, no chatbot round-trip.
2. **Copy-paste prompts** — Free option for users with own LLMs. More flexible, can adapt prompts.

Both will exist. Gemini for convenience, copy-paste for free/flexible.

## Non-goals

- **Custom user prompts** — Users cannot write their own prompts. We provide 1-3 in-house templates. At most: toggles for specific options (e.g., remove reference section). Users can copy templates to adapt for their own LLM if they want flexibility.

## Cost reality check

Gemini 3 pricing looks cheaper on paper but need to monitor actual costs per page as prompts evolve. Likely need to reduce OCR/processing limits:

| Plan | Current OCR | New Processing (tentative) |
|------|-------------|---------------------------|
| Basic | 500 | ~300 |
| Pro | 1500 | ~1000 |
| Max | 3000 | ~2000 |

TODO: Calculate actual expected costs before finalizing.


## Decision: Gemini 3 Flash for integrated option

**Winner:** Gemini 3 Flash — cheaper than Mistral, provides transformation.

### Pricing comparison (per 1000 pages)

| Option | Cost | Notes |
|--------|------|-------|
| Gemini 3 Flash (low) | ~$1.40 | transformation included |
| Gemini 3 Flash (high) | ~$1.70 | transformation included |
| Mistral OCR | ~$2.00 | extraction only |
| Claude Haiku batch | ~$4.50 | too expensive |

### Considered & rejected

- **Claude Haiku/Sonnet** — 3-6x more expensive than Mistral. Was the "fourth option" before Gemini research.
- **DeepSeek VL2** — Cheapest but quality inconsistency, latency concerns.
- **Qwen 2.5 VL** — Good multilingual but latency issues.
- **GPT-4o** — More expensive than Claude.

## Gemini 3 Flash — Technical Findings

**How it processes PDFs:**
- Native vision (pages as images) + embedded text extraction
- Native text is FREE (not charged)
- Image tokens charged by `media_resolution`
- **Limits: 50MB or 1000 pages** — handle in frontend/backend

**Model:** `gemini-3-flash-preview`

**Resolution token costs (empirical, prompt ~110 tokens):**

| Resolution | Input Tokens/page | Image Tokens |
|------------|-------------------|--------------|
| Low | 377 | ~267 |
| Medium (default) | 631 | ~521 |
| High | 1213 | ~1103 |

**Experiment location:** `experiments/gemini-flash-doc-transform/`

## Implementation Ideas

**Prompt principles (for subtask):**
- Accurate extraction first, minimal transformation
- Links can stay — our frontend md processor handles them
- Math → LaTeX (katex renders it)
- Inline spoken math ("x squared") = future toggle, not base prompt
- Reference-only pages → maybe "References skipped"
- User presets/templates for document types (arXiv, textbook, etc.)

**Integration thoughts:**
- Probably replace Mistral entirely (less moving parts)
- Resolution as user toggle? Affects quota. TBD based on benchmarking.
- Chunking: page-by-page for now, most pages self-contained
- Page breaks in sentences: handle via prompting or post-processing

**Frontend ideas:**
- User-editable prompt templates
- Presets for document types
- Security if user prompts allowed

## Original Context

Started as "LLM Preprocessing Prompt for Users" — providing copy-paste prompts for users to preprocess complex documents with their own LLM.

Research into "fourth option" (integrated LLM) led to discovering Gemini 3 Flash is cheaper than Mistral OCR while providing transformation.

**Use cases driving this:**
- LaTeX/math notation → readable prose or proper LaTeX
- Academic papers, textbooks — accurate extraction
- Links, tables, figures — handle appropriately

## Sources

**Gemini:**
- [Document Processing](https://ai.google.dev/gemini-api/docs/document-processing)
- [Media Resolution](https://ai.google.dev/gemini-api/docs/media-resolution)
- [Models](https://ai.google.dev/gemini-api/docs/models)
- [Pricing](https://ai.google.dev/gemini-api/docs/pricing)

**Other:**
- [Claude Pricing](https://claude.com/pricing)
- [Mistral OCR 3](https://mistral.ai/news/mistral-ocr-3)
- [VLM Comparison 2025](https://www.analyticsvidhya.com/blog/2025/11/deepseek-ocr-vs-qwen-3-vl-vs-mistral-ocr/)

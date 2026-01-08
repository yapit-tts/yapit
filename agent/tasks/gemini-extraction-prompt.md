---
status: active
started: 2025-01-08
---

# Task: Draft TTS-Optimized Extraction Prompt for Gemini 3 Flash

## Intent

Replace Mistral OCR with Gemini 3 Flash for document processing. The prompt should prioritize **accurate extraction** over transformation — Gemini should faithfully extract the document content as clean markdown, not reinterpret or heavily transform it.

Key principles (from user):
- **Accurate original text extraction is priority #1** — don't alter meaning, don't interpret
- **Minimal transformation** — keep more intact rather than removing too much
- Links CAN be kept — our frontend markdown processor handles them (not everything is read aloud)
- Math → LaTeX syntax (`$inline$` and `$$display$$`) for katex frontend rendering
- Inline math that can be spoken could become "x squared" but that's a future customization toggle, not base prompt
- Layout/structure changes are OK to fit markdown format
- Consider: should reference-only pages output "References skipped" or similar?

Future vision (not first iteration):
- Frontend toggles for customization (remove references, expand math to speech, etc.)
- User-editable prompt templates (arXiv preset, textbook preset, etc.)

## Sources

**MUST READ — Parent task:**
- [[llm-preprocessing-prompt]] — research context, pricing analysis, decision rationale for Gemini

**MUST READ — Backend pipeline (output format requirements):**
- `yapit/gateway/processors/markdown/parser.py` — markdown parser config (CommonMark + GFM tables + dollar math + strikethrough)
- `yapit/gateway/processors/markdown/transformer.py` — converts AST → StructuredDocument, see how math/links/etc are handled
- `yapit/gateway/processors/document/mistral.py` — current OCR processor, returns `{page_idx: ExtractedPage(markdown=..., images=[...])}`

**MUST READ — Existing experiment:**
- `experiments/gemini-flash-doc-transform/` — working code, current prompt, sample outputs

**Research (prompting best practices):**
- Anthropic prompt guide: https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/overview
- Google Gemini docs (document processing): https://ai.google.dev/gemini-api/docs/document-processing
- Google Gemini docs (prompting): https://ai.google.dev/gemini-api/docs/prompting-strategies

## Output Format Requirements (from codebase analysis)

**Markdown parser supports:**
- CommonMark (standard markdown)
- GFM tables (`| header | header |`)
- Dollar math: `$inline$` and `$$display$$` (via `dollarmath_plugin`)
- Strikethrough: `~~text~~`

**How content is processed for TTS:**

| Content Type | Visual Rendering | TTS Behavior |
|--------------|------------------|--------------|
| Headings | Rendered | Read aloud |
| Paragraphs | Rendered | Read aloud |
| Lists | Rendered | Read aloud |
| Blockquotes | Rendered | Nested blocks read aloud |
| Links | Clickable `<a>` tag | Link text read, href ignored |
| Inline math | Katex rendered | **Currently skipped** (empty string) |
| Display math | Katex rendered | No audio (non-prose block) |
| Code blocks | Syntax highlighted | No audio (non-prose block) |
| Tables | Rendered | No audio (non-prose block) |
| Images | Rendered | Alt text used if any |

**Implication for prompt:**
- Math in LaTeX is fine — it's rendered visually, just not read aloud (current behavior)
- Links can be kept — frontend shows them, TTS reads link text only
- Tables can be kept as markdown tables — they render but aren't read
- Code blocks can be kept — they render but aren't read

## Current Experiment State

The current prompt in `experiments/gemini-flash-doc-transform/prompt.txt` is **transformation-focused** (not what we want):

```
Extract and transform this document page for text-to-speech. Output clean markdown that sounds natural when read aloud.

Instructions:
1. Convert math/LaTeX to spoken form (e.g., "x^2" → "x squared", "∑" → "sum of")
2. Remove URLs and hyperlinks, keep descriptive text
3. Describe or summarize complex tables/figures briefly
4. Expand abbreviations on first use
5. Keep the meaning intact, optimize for listening

Output only the transformed markdown, no commentary.
```

**Problem:** Sample output shows heavy transformation (e.g., "28.4 BLEU" → "twenty-eight point four B L E U"). This loses accuracy and isn't what we want for the base prompt.

## Prompt Design Considerations

### 1. Start slim, focused on accurate extraction

The base prompt should be minimal and focus on faithful extraction. Transformation features (math expansion, reference removal, etc.) come later as user-selectable toggles.

### 2. Whether to include examples

**Pros:** Helps model understand exact expected format
**Cons:** Adds tokens (cost), may over-constrain

**Recommendation:** Start without examples. Add targeted examples only if quality issues emerge.

### 3. LaTeX formatting

Be explicit about LaTeX syntax expectations:
- Inline: `$x^2$` not `\(x^2\)`
- Display: `$$\sum_{i=1}^n x_i$$` not `\[\sum...\]`

### 4. Reference pages

Options:
- Extract references normally (they'll render but not be read aloud anyway)
- Output "References skipped" or similar
- Let user control via toggle (future)

**Recommendation:** For base prompt, extract normally. References are non-prose anyway.

### 5. Multi-page stitching

Pages are processed individually, then concatenated with `<!-- Page N -->` markers. The prompt should produce markdown that stitches cleanly.

## Prompt v1 (tested, working)

Location: `experiments/gemini-flash-doc-transform/prompts/v1.txt`

```
Extract the text from this document page as clean markdown.

Rules:
- Preserve the original text exactly — do not paraphrase, interpret, or rewrite
- Use standard markdown formatting (headings, lists, emphasis, bold, etc.)
- Mathematical notation: use LaTeX with dollar signs ($inline$ for inline, $$display$$ for display)
- Keep hyperlinks in markdown format: [text](url)
- Tables: use markdown table syntax
- Skip page numbers, headers/footers, and watermarks

Output only the markdown, no commentary or explanations.
```

## Test Results (2025-01-08)

**Test:** "Attention Is All You Need" paper, pages 1-10, low resolution

**Cost:** $0.0279 total (~$0.0028/page) — cheaper than Mistral OCR!

**Comparison v0 (transformation) vs v1 (extraction):**

- v0 (transformation): "twenty-eight point four B L E U", "W M T twenty-fourteen" — spelled out
- v1 (extraction): "28.4 BLEU", "WMT 2014" — preserved as original ✓

- v0: Emails removed, affiliations grouped
- v1: All author emails and individual affiliations preserved ✓

- v0: Math converted to speech
- v1: LaTeX preserved: `$h_t$`, `$$\text{Attention}(Q,K,V) = ...$$` ✓

- v0: Citations sometimes lost
- v1: Citations preserved: [13], [7], etc. ✓

**Verdict:** v1 extraction-focused prompt works well. Math properly formatted with dollar signs for katex. Original content preserved accurately.

## Gotchas

- The key instruction: "Preserve the original text exactly — do not paraphrase, interpret, or rewrite"
- Model ID is `gemini-3-flash-preview` (may change)
- Low resolution (~$0.0028/page) is sufficient for text-heavy academic papers

## Next Steps

1. **Test on more document types** — textbooks, web articles, documents with heavy tables
2. **Test reference pages** — do they get extracted cleanly or need special handling?
3. **Integration** — create a Gemini document processor similar to `mistral.py`
4. **Consider prompt variations** for future toggles:
   - `v2-no-references.txt` — skip references section
   - `v2-math-spoken.txt` — expand math to spoken form

## Handoff

Prompt v1 is ready for integration. Run with:
```bash
cd experiments/gemini-flash-doc-transform
GOOGLE_API_KEY=... uv run process_pdf.py -v v1 --pages 1-10 --resolution low
```

Output: `experiments/gemini-flash-doc-transform/output/v1/{doc}.md`

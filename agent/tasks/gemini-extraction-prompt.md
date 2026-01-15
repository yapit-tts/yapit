---
status: done
started: 2025-01-08
completed: 2026-01-15
pr: https://github.com/yapit-tts/yapit/pull/56
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
- [Google Gemini Prompting Strategies](https://ai.google.dev/gemini-api/docs/prompting-strategies)
- [Gemini 3 Prompting Guide (Vertex AI)](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/start/gemini-3-prompting-guide)
- [Claude 4 Best Practices](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-4-best-practices)
- [Google Document Processing](https://ai.google.dev/gemini-api/docs/document-processing)

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

## Prompt v2 (with image placeholders)

Location: `experiments/gemini-flash-doc-transform/prompts/v2.txt`

Adds image placeholder handling for figure extraction. See [[gemini-integration-exploration]] for the full pipeline with PyMuPDF image extraction.

## Prompting Research Findings

Key insights relevant to document extraction:

**1. Few-shot examples strongly recommended**
- Google: "Prompts without few-shot examples are likely to be less effective"
- 2-5 varied examples, show positive patterns (what TO do)
- **For now:** Wait until we see actual edge cases before adding

**2. Say what TO do, not what NOT to do**
- Gemini 3: "Providing open-ended system instructions like 'do not infer' may cause the model to over-index"
- Instead of "do not paraphrase" → "preserve the original text exactly"
- Our v1/v2 prompts already follow this pattern

**3. Add context explaining WHY**
- Anthropic: "Providing context or motivation behind your instructions can help"
- Example: "Your response will be read aloud by a text-to-speech engine, so..."
- **TODO for v3:** Add TTS context to help model understand the use case

**4. Place critical constraints at END**
- Gemini 3: Complex requests may cause model to "drop negative constraints appearing too early"
- Our prompt already puts output instruction last

**5. Grounding instruction**
- Google: "You are a strictly grounded assistant limited to the information provided"
- Could add: "Extract only what's present in the document"

**6. Temperature**
- Gemini 3 recommends default 1.0, warns lowering can cause issues for reasoning tasks
- For pure extraction: unknown whether lower helps. Start with default, test if needed.

## Known Issues (v2)

**Inconsistent inline math LaTeX:**
- Example: "length penalty α = 0.6 [38]" — should be `$\alpha = 0.6$`
- Model sometimes uses unicode symbols instead of LaTeX
- Also: `d_k` should be `$d_k$`

**Symbols without pronunciation:**
- Daggers (†, ‡) for author affiliations — could be LaTeX `$\dagger$`, `$\ddagger$`
- These have no TTS pronunciation, so visual-only rendering makes sense

**Citations [38]:**
- Currently preserved — could be toggleable (remove references toggle)

## Future Ideas

### Inline math with spoken alternative

**Problem:** Inline math like `$d_k$` renders visually but creates gaps in TTS audio (transformer returns empty string for `math_inline`).

**Idea:** Have Gemini output both render format AND spoken text:
```
$d_k${d sub k}
$\alpha = 0.6${alpha equals 0.6}
```

**Implementation would require:**
1. New format in prompt (braces won't conflict with real content)
2. New `InlineMathContent` model with `latex` and `spoken` fields
3. Transformer changes to parse format and keep spoken text in `plain_text`

**Decision:** Keep simple for now. Just use consistent LaTeX. Add spoken alternative later if the gaps become annoying. This is a toggleable feature for the future.

### Image storage

**Problem:** Base64 data URLs in markdown are terrible for export (copy/download).

**Solution:** Store extracted images at `yapit.md/images/{doc-id}/{img-index}.png`
- Real URLs work everywhere (copy, export, share)
- No frontend filtering needed
- Images deleted when document is deleted
- Could be CDN-cached for performance

## v3 Prompt Direction

Focus for next iteration:
1. **TTS context** — explain the markdown will be rendered and only text content read aloud
2. **Consistent LaTeX** — emphasize using LaTeX for ALL mathematical notation, symbols without pronunciation
3. **Specific examples** — only if edge cases emerge from more testing

## Gotchas

- The key instruction: "Preserve the original text exactly — do not paraphrase, interpret, or rewrite"
- Model ID is `gemini-3-flash-preview` (may change)
- Low resolution (~$0.0028/page) sufficient for text-heavy papers, medium may be better (see [[gemini-integration-exploration]])

## Handoff

Run experiments with:
```bash
cd experiments/gemini-flash-doc-transform
GOOGLE_API_KEY=... uv run process_pdf.py -v v2 --pages 1-10 --resolution medium
```

Output: `experiments/gemini-flash-doc-transform/output/{version}/{doc}.md`

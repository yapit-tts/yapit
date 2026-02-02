---
status: active
started: 2026-01-14
---

- NOTE: When we implement this, we should cleanup the documents.py code... processors shoud have extract_webpage and extract_pdf or sth similar, rather than calling markitdown directly in documents.py as we do rn.

# Task: AI Transform Retry for Webpages

## Intent

Add ability to retry webpage processing with Gemini after initial MarkItDown extraction. Users paste a URL → see instant (free) MarkItDown result → if math/formatting is mangled, can click "Retry with AI Transform" while original HTML is still in file cache.

**The problem:** MarkItDown mangles math-heavy pages. It extracts both Unicode-rendered math AND LaTeX source, concatenating them into garbage like:
```
x​(t)∈ℝ↦y​(t)∈ℝx(t)\in\mathbb{R}\mapsto y(t)\in\mathbb{R}
```

**The solution:** Re-process original HTML with Gemini, which properly extracts LaTeX from MathML `alttext`/`annotation` attributes:
```
$x(t)\in\mathbb{R}\mapsto y(t)\in\mathbb{R}$
```

**Value prop:** Try-before-you-buy UX. User sees free result first, only pays if they want better extraction.

## Assumptions

- File cache is LRU-based (no TTL) — try cache first, re-fetch from stored URL as fallback
- If re-fetching, page content may have changed — acceptable tradeoff
- LaTeX source is preserved in HTML for major math sources (arXiv, Wikipedia) — verified empirically
- Text input (pasted markdown/text) does NOT get this feature — nothing to "fix"

## Sources

**Knowledge files:**
- [[document-processing]] — current URL → MarkItDown → document flow
- [[gemini-processor-integration]] — Gemini extraction patterns, billing model

**Key code files:**
- MUST READ: `yapit/gateway/api/v1/documents.py` — `create_website_document()`, file cache usage
- MUST READ: `frontend/src/components/unifiedInput.tsx` — current URL input flow
- Reference: `yapit/gateway/cache.py` — LRU cache implementation
- Reference: `frontend/src/pages/PlaybackPage.tsx` — where retry button would go

**Experiment results:**
- arXiv HTML: 180-370KB (~46-92K tokens), LaTeX in `alttext` + `<annotation encoding="application/x-tex">`
- Wikipedia: 300KB (~75K tokens), LaTeX in `alttext`
- No SVG bloat observed in major math sources
- Gemini extraction test: clean output with proper `$...$` and `$$...$$` formatting

## Key Decisions

### From Brainstorming

- **Re-extract from HTML, not fix markdown** — Fixing mangled markdown is unreliable/lossy. Re-processing original HTML gives Gemini access to preserved LaTeX source.
- **Different prompt than PDF extraction** — PDFs use visual extraction. Webpages need: "Extract LaTeX from MathML alttext/annotation, format as markdown with $...$ delimiters"
- **Billing: same rate as PDFs** — 1 virtual page = ~2K tokens of HTML content. Process in larger batches (8-16K tokens) to amortize prompt overhead, but bill per 2K chunk.
- **Update document in-place** — Don't create new document. If user wants to compare, they can re-paste URL.
- **Text input excluded** — No retry for pasted text (nothing to re-extract from)

### Open (UX)

- **Button placement:** Options discussed:
  - Banner at top (like failed pages banner) — potentially annoying for all docs
  - In document header near source URL — less intrusive
  - Three-dots menu in sidebar — discoverable but hidden
  - Mention in /tips page
- **Availability window:** Show button only while HTML is in cache? Or always show and re-fetch if needed?
- **Heuristics:** Could detect if page likely has math (presence of MathML/LaTeX patterns) to decide whether to show button prominently

## Done When

- [ ] Backend: New endpoint `POST /v1/documents/{document_id}/enhance`
  - Validates: must be URL-based doc with `extraction_method == "markitdown"`
  - Retrieves HTML from file cache (or re-fetches URL as fallback)
  - Processes with Gemini using webpage-specific prompt
  - Updates document's `original_text`, `structured_content`, `extraction_method`
  - Handles billing (same rate as PDF pages)
- [ ] Backend: HTML preprocessing — strip scripts/nav/styling, keep article content
- [ ] Backend: Chunking for large pages — split by HTML tag boundaries, ~2K tokens per virtual page
- [ ] Frontend: UI for triggering retry (placement TBD)
- [ ] Frontend: Cost estimate display before confirm (shows virtual page count)
- [ ] Frontend: Progress indication during processing (counter or progress bar)
- [ ] Frontend: Document content updates after successful enhancement
- [ ] Prompt: Webpage-specific extraction prompt (different from PDF visual extraction)

## Technical Notes

### HTML Preprocessing

Need to strip boilerplate before sending to Gemini:
- Remove `<script>`, `<style>`, `<nav>`, `<header>`, `<footer>` tags
- Keep `<article>`, `<main>`, `<section>` content
- Preserve `<math>` tags with their `alttext` and `annotation` children

Could potentially use MarkItDown's HTML parsing as preprocessor, or BeautifulSoup/lxml.

### Chunking Strategy

- Split on HTML tag boundaries (not mid-tag)
- Natural break points: `</section>`, `</article>`, `<h1>`-`<h6>`
- Target ~2K tokens per chunk for billing, but batch 4-8 chunks per API call
- Always show cost estimate before confirm (webpage "page count" is unpredictable upfront)
- Progress indication during processing (similar to PDF extraction progress bar, or simpler counter)

### Cache Fallback

If file cache miss (HTML evicted):
1. Check `document.metadata_dict.url` exists
2. Re-fetch URL
3. Process with Gemini
4. Note: page content might have changed — acceptable tradeoff

## Considered & Rejected

- **Fix mangled markdown instead of re-extracting** — Lossy transformation, can't reliably reconstruct complex LaTeX from garbled output
- **Store raw HTML in Document** — Expensive storage for rarely-used feature, file cache is sufficient
- **Retry for pasted text** — No source to re-extract from, user's text is already what they wanted

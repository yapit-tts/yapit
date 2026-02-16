---
status: done
started: 2026-02-02
---

# Task: Website Experience Improvements

## Intent

Improve the end-to-end experience for website URLs — from content extraction quality to optional AI enhancement. Currently, MarkItDown converts ALL visible HTML (including nav, sidebars, footers, cookie banners) into markdown that gets read aloud. Citations like `[42]` are also read as literal text. This is the biggest quality gap in the product.

Two-tier approach: make the free path much better with content extraction, and offer Gemini transform for pages that need semantic understanding (math, citations, complex formatting).

## Workstreams

### 1. Trafilatura Content Extraction (DONE)

Replace raw MarkItDown as the primary website processor with trafilatura, which strips boilerplate (nav, sidebar, footer, related articles, etc.) and extracts article content. Use `output_format='markdown'` directly into our parser.

Fallback to current MarkItDown path if trafilatura returns `None` (non-article pages, forums, etc.).

**Known limitation:** Inline citation markers (`[1]`, `[42]`) survive as text noise. This is inherent — rules can't do context-dependent citation handling. Acceptable tradeoff for the free tier; Gemini transform addresses it for users who care.

Trafilatura works on static HTML only — our existing Playwright JS-rendering detection stays in the pipeline (render first if needed, then extract).

### 2. Gemini Webpage Transform (paid, opt-in)

Extends [[2026-01-14-ai-transform-retry-webpages]] beyond math to general webpage quality: citation handling (`<yap-show>` wrapping, author naturalization), reference section omission, footnote conversion to `[^N]` syntax, cross-page bibliography silencing.

Separate prompt from PDF extraction but sharing the yap-tag spec and many formatting rules from the existing extraction prompt. Key difference: PDF prompt does visual extraction from page images; webpage prompt processes HTML/text with semantic understanding.

Same UX pattern as PDF: user sees free result first, opts in to AI transform if quality isn't sufficient. Costs credits.

### 3. `yapit.md/URL` Routing (DONE)

Catch-all route where `yapit.md/example.com/page` creates a document from the URL and lands on playback (or prepare page for PDFs). Near-zero implementation cost — frontend catch-all route + existing backend helpers.

Primary value: integration point for third-party apps (e.g., friend's Onyx static site generator — one-button redirect to yapit). Secondary: slightly nicer shared URLs (shows webpage URL instead of UUID).

## Assumptions

- Trafilatura's markdown output is compatible with our markdown-it parser (standard CommonMark + extensions)
- `favor_precision` vs `favor_recall` made no difference on test pages — default settings are fine initially
- Trafilatura is a new dependency (~moderate footprint: lxml, jusText, courlan, htmldate, charset_normalizer)
- The Gemini webpage prompt will share structure with the PDF extraction prompt but diverge on input handling (HTML text vs page images)

## Sources

**Knowledge files:**
- [[document-processing]] — current URL → MarkItDown → document flow
- [[frontend]] — outliner (section skipping), playback engine
- [[tts-flow]] — synthesis pipeline context
- [[markdown-parser-spec]] — yap-tag semantics, footnote handling

**Key code files:**
- MUST READ: `yapit/gateway/api/v1/documents.py` — `_extract_website_content()`, `create_website_document()`, prepare flow
- MUST READ: `yapit/gateway/document/prompts/extraction.txt` — existing Gemini prompt (citation/footnote/reference rules at lines 107-123)
- MUST READ: `frontend/src/components/unifiedInput.tsx` — URL input flow, auto-creation for websites
- Reference: `yapit/gateway/document/http.py` — URL fetching, content-type sniffing
- Reference: `yapit/gateway/document/playwright_renderer.py` — JS rendering detection
- Reference: `yapit/gateway/markdown/transformer.py` — footnote ref handling (silent in TTS), block transformation

**External:**
- Reference: [Trafilatura docs](https://trafilatura.readthedocs.io/) — `extract()` API, output formats, configuration options
- Reference: [Trafilatura evaluation](https://trafilatura.readthedocs.io/en/latest/evaluation.html) — F1=0.958 on ScrapingHub benchmark

**Experiment results (this session):**
- Trafilatura strips ~10k chars of boilerplate on Antikythera chapter (68k vs 78k raw MarkItDown)
- Raw MarkItDown duplicates footnote content; trafilatura doesn't
- Inline citation markers survive in all rules-based approaches — confirmed semantic understanding needed
- Trafilatura returns `None` on some pages (by design) — MarkItDown fallback required
- Wikipedia needs trafilatura's own fetcher or realistic UA (our httpx fetch works fine though)

## Done When

- [x] Trafilatura integrated as primary website content extractor with MarkItDown fallback
- [ ] Gemini webpage transform endpoint and prompt (opt-in, same UX as PDF AI extraction)
- [x] `yapit.md/URL` catch-all routing (low priority, can be separate PR)

## Considered & Rejected

- **Transformer-level citation heuristic** (regex to detect `[N]` patterns) — too brittle, false positives on legitimate bracket usage, can't handle context-dependent cases like "As [1] showed"
- **Auto-detection for Gemini transform** — costs credits, user must opt in (same reason as PDF)
- **Auto-skip metadata sections in outliner** — a crutch; proper content extraction (trafilatura) is the real fix
- **Trafilatura HTML → MarkItDown hybrid pipeline** — extra conversion step for marginal benefit over trafilatura's direct markdown output

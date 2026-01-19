---
status: active
started: 2026-01-19
---

# Task: Implement `<yap-show>` tag for display-only text

## Intent

Add a new annotation tag that allows text to be displayed but not spoken (or spoken differently). This mirrors how math works (`$latex$<yap-alt>spoken</yap-alt>`) but for regular text.

Primary motivation: citations. Bulk refs like `[1, 2, 3]` are noise when read aloud, but should remain visible. Author citations like `(Smith et al., 2020)` should display verbatim but can be naturalized for speech.

## Design

**Syntax:**
```markdown
<yap-show>displayed text</yap-show>
```
→ Displayed, not spoken (silent)

```markdown
<yap-show>displayed text</yap-show><yap-alt>spoken text</yap-alt>
```
→ Displayed as "displayed text", spoken as "spoken text"

**Same-line requirement** like other yap tags.

**Content inside `<yap-show>`** should support inline formatting (bold, italic, latex with its own yap-alt) — treat like regular inline text, not plain string.

## Primary Use Case: Citations

```markdown
As <yap-show>(Smith et al., 2020)</yap-show><yap-alt>Smith and colleagues</yap-alt> showed, ...
```
→ Display: "As (Smith et al., 2020) showed, ..."
→ Speech: "As Smith and colleagues showed, ..."

```markdown
This has been studied extensively <yap-show>[1, 2, 3]</yap-show>.
```
→ Display: "This has been studied extensively [1, 2, 3]."
→ Speech: "This has been studied extensively."

## Potential Future Use Cases

(Don't over-engineer for these — note for reference)
- Footnote markers: `<yap-show>¹</yap-show>` — visual, silent
- Inline asides: `<yap-show>(see Appendix A)</yap-show>` — nav aid, not spoken
- URLs: `<yap-show>https://example.com</yap-show><yap-alt>the project website</yap-alt>`

## Implementation

### 1. Prompt update (`extraction.txt`)
Add `<yap-show>` section with examples for citations.

### 2. Transformer (`transformer.py`)
- Parse `<yap-show>...</yap-show>` as html_inline nodes (like yap-cap, yap-alt)
- Extract content, check for following `<yap-alt>`
- For plain_text extraction (TTS): use yap-alt if present, otherwise skip entirely
- For HTML rendering: render the inner content normally

### 3. Frontend (`structuredDocument.tsx`)
- Render `<yap-show>` content as regular text
- Hover behavior (if yap-alt present): show tooltip with spoken text, or animate text swap (stretch goal)
- If no yap-alt (silent): no special hover, just render

## Sources

**Related tasks:**
- [[2026-01-15-tts-annotation-syntax-pivot]] — established `<yap-alt>` and `<yap-cap>` pattern, parsing approach

**Knowledge files:**
- [[document-processing]] — how markdown gets transformed

**Key code files:**
- MUST READ: `yapit/gateway/document/prompts/extraction.txt` — current prompt
- MUST READ: `yapit/gateway/markdown/transformer.py` — parsing logic for yap tags (see `_extract_yap_alt`, `_extract_yap_cap` helpers)
- MUST READ: `frontend/src/components/structuredDocument.tsx` — rendering

## Done When

- [ ] Gemini outputs `<yap-show>` for citations per prompt guidance
- [ ] Transformer extracts display vs speech text correctly
- [ ] Frontend renders displayed text, excludes from TTS
- [ ] Hover shows spoken text (or indicates silent)

## Considered & Rejected

**Empty link hack `[](citation)`**: Unclean — links have semantic meaning, would need frontend hacks to display href, doesn't generalize.

**`<yap-silent>` naming**: Implies no-speech only, but adding `<yap-alt>` then feels odd. `<yap-show>` focuses on what's *shown*, speech controlled separately.

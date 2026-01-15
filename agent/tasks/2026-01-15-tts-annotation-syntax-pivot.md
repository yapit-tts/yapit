---
status: done
started: 2026-01-15
completed: 2026-01-15
---

# TTS Annotation Syntax

## Problem

When a VLM extracts text from documents, certain content needs **alternative text for TTS**:

1. **Math expressions** — `$\alpha$` should be spoken as "alpha"
2. **Figure captions** — Images need scholarly captions read aloud
3. **Nested case** — Captions can contain math, each needing its own alt

**Core issue:** Markdown has no native way to attach metadata to arbitrary elements.

### Failed approaches

| Syntax | Problem |
|--------|---------|
| `{tts:...}` | Conflicts with LaTeX braces: `{tts:$\{\mathcal{C}\}$}` breaks |
| `<tts>...</tts>` (single tag) | Nesting breaks: `<tts>caption <tts>math alt</tts></tts>` — regex stops at first `</tts>` |

## Solution: Distinct Tags

Use different tags for different annotation types:

- `<yap-alt>` — Math alt text (short, inline)
- `<yap-cap>` — Figure captions (can contain math with `<yap-alt>` inside)

Nesting is unambiguous because we match `</yap-cap>`, which is distinct from `</yap-alt>`.

## Format

### Inline math
```markdown
We study $\alpha$<yap-alt>alpha</yap-alt> values.
```

### Display math
```markdown
$$E = mc^2$$
<yap-alt>E equals m c squared</yap-alt>
```

### Image with caption (no math)
```markdown
![Diagram of method](url)<yap-cap>Figure 1 | Overview of the approach</yap-cap>
```

### Image with caption containing math
```markdown
![Diagram](url)<yap-cap>Figure 1 shows $\beta$<yap-alt>beta</yap-alt> dynamics</yap-cap>
```

## How markdown-it Handles This

Custom tags like `<yap-alt>` and `<yap-cap>` are treated as **inline HTML** (not block HTML) because they're not in markdown-it's hardcoded list of block-level tags (div, p, table, etc.).

For `![](url)<yap-cap>Caption with $\beta$<yap-alt>beta</yap-alt> text</yap-cap>`:

```
image: src=url
html_inline: <yap-cap>
text: "Caption with "
math_inline: \beta
html_inline: <yap-alt>
text: "beta"
html_inline: </yap-alt>
text: " text"
html_inline: </yap-cap>
```

Math inside custom tags IS parsed by the dollarmath plugin. ✅

### Constraint: No newlines inside tags

If content has newlines inside the tag, it becomes `html_block` and inner content is NOT parsed for markdown. Prompt instructs VLM to keep content on single lines.

## Implementation

Helper functions added to `transformer.py`:
- `_is_html_tag()` — Check if node is a specific HTML tag
- `_extract_yap_alt()` — Extract `<yap-alt>...</yap-alt>` spans, returns (alt_text, nodes_consumed)
- `_extract_yap_cap()` — Extract `<yap-cap>...</yap-cap>` spans, returns (caption_nodes, nodes_consumed)
- `_extract_plain_text_from_caption_nodes()` — Get (display_text, tts_text) from caption nodes

Key insight: Use depth counter in `_is_standalone_image()` to handle nested tags correctly.

## Files Changed

| File | Change |
|------|--------|
| `extraction_v1.txt` | Updated syntax, added nested example, "no newlines" instruction |
| `extraction.py` | Updated `IMAGE_PLACEHOLDER_PATTERN` for `<yap-cap>` |
| `transformer.py` | Added helper functions, updated all annotation extraction points |
| `test_markdown.py` | Added `TestYapAnnotations` class with 7 tests |

## Done

- [x] Prompt uses `<yap-alt>` and `<yap-cap>` syntax
- [x] Annotation extraction handles nested tags via depth tracking
- [x] Transformer extracts captions with `_extract_yap_cap`, math alts with `_extract_yap_alt`
- [x] Test: math-heavy figure caption renders correctly AND has correct TTS
- [x] Test: inline math, display math, image captions all work
- [x] Unit tests added for annotation handling

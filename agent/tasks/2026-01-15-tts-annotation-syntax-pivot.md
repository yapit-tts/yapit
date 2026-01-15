---
status: active
started: 2026-01-15
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

If content has newlines inside the tag:
```markdown
<yap-cap>Long caption
with newlines</yap-cap>
```
...it becomes `html_block` and inner content is NOT parsed for markdown.

**Prompt must instruct:** Keep `<yap-alt>` and `<yap-cap>` content on a single line.

## Implementation

### 1. Update prompt (`extraction_v1.txt`)

```
Images:
- Format: ![alt](detected-image)<yap-cap>caption</yap-cap>
  - alt = short visual description
  - <yap-cap>...</yap-cap> = figure caption (omit if none)

Math TTS — use <yap-alt>...</yap-alt>:

INLINE: $latex$<yap-alt>alt</yap-alt>
  Example: $\alpha$<yap-alt>alpha</yap-alt>

DISPLAY: $$latex$$ then <yap-alt>alt</yap-alt> on next line
  Example:
    $$E=mc^2$$
    <yap-alt>E equals m c squared</yap-alt>

Captions may contain math — use <yap-alt> inside <yap-cap>:
  <yap-cap>Figure 1 shows $\beta$<yap-alt>beta</yap-alt> values</yap-cap>

IMPORTANT: Keep all annotation content on a single line (no line breaks inside tags).
```

### 2. Token post-processor

Add a phase between markdown-it parsing and block transformation:

```python
def process_annotations(tokens: list[Token]) -> list[Token]:
    """
    Walk token stream, attach annotations to elements:
    - <yap-alt>...</yap-alt> after math_inline → attach as meta['alt']
    - <yap-cap>...</yap-cap> after image → extract caption, handle nested <yap-alt>
    """
```

This replaces the scattered annotation extraction currently in transformer.py.

### 3. Simplify transformer

Remove `_extract_annotation()` calls from transform methods. Instead, read from `token.meta['alt']` and `token.meta['caption']` which are already attached by the post-processor.

## Files to Change

| File | Change |
|------|--------|
| `yapit/gateway/processors/document/prompts/extraction_v1.txt` | Update syntax examples |
| `yapit/gateway/processors/document/extraction.py` | Update `IMAGE_PLACEHOLDER_PATTERN` |
| `yapit/gateway/processors/markdown/transformer.py` | Add post-processor, remove scattered extraction |

## Done When

- [ ] Prompt uses `<yap-alt>` and `<yap-cap>` syntax
- [ ] Post-processor extracts and attaches annotations
- [ ] Transformer reads from token.meta instead of parsing inline
- [ ] Test: math-heavy figure caption renders correctly AND has correct TTS
- [ ] Test: inline math, display math, image captions all work

# Tag Inventory

| Tag | Purpose | Display | TTS |
|---|---|---|---|
| `<yap-show>content</yap-show>` | Show but don't speak | ✅ content | ❌ silent |
| `<yap-speak>content</yap-speak>` | Speak but don't show | ❌ hidden | ✅ content |
| `<yap-cap>content</yap-cap>` | Image caption | ✅ content | ✅ content |

# Footnotes

**Syntax:** `text[^label]` for refs, `[^label]: content` for definitions

| Element | Display | TTS |
|---|---|---|
| `[^1]` (ref) | Superscript link to footnote | ❌ silent |
| `[^1]: content` (definition) | Footnote section at document end | ✅ content |

**Behavior:**
- Refs render as `<sup class="footnote-ref"><a href="#fn-{label}">[label]</a></sup>`
- Definitions collected in `FootnotesBlock` at document end
- Backlinks (↩) from footnotes to refs
- Cross-page deduplication: colliding labels renamed to `p{N}-{label}`

**Edge cases:**
- Ref without content → plain text superscript (no link)
- Content without ref → displayed but dimmed (orphan footnote)

# Callouts

**Syntax:** `> [!COLOR] Optional Title` followed by blockquote content

**Colors:** BLUE, GREEN, PURPLE, RED, YELLOW, TEAL

| Element | Display | TTS |
|---|---|---|
| Title | Colored header | ✅ title text |
| Content | Colored blockquote | ✅ content |

Colors are purely visual styling — pick based on aesthetics, not semantic meaning. This deliberately avoids the NOTE/WARNING/TIP pattern from dev docs.

# Core Rules

1. Math is always silent  
   - `$latex$` renders visually but contributes nothing to TTS  
   - Pronunciation is provided by adjacent `yap-speak`: `$\alpha$<yap-speak>alpha</yap-speak>`

2. `yap-show` creates a display-only zone  
   - Everything inside goes to display, nothing to TTS  
   - Nested tags (including `yap-speak`) are also display-only  
   - For TTS, put `yap-speak` AFTER the closing tag:  
     `<yap-show>X</yap-show><yap-speak>Y</yap-speak>`

3. `yap-speak` is independent content  
   - NOT attached to a preceding element — it is just content that appears in TTS  
   - Can appear anywhere: after math, standalone, after `yap-show`

4. `yap-cap` is a caption container  
   - Must immediately follow an image: `![alt](url)<yap-cap>...</yap-cap>`  
   - Supports full inline markdown: **bold**, links, math, `yap-show`, `yap-speak`  
   - Both display and TTS come from caption content (with tag routing applied)

# Placement Rules / Quirks

Same-line requirement:  
- All yap tags must be on the same line as their content  
- No newlines inside `<yap-show>...</yap-show>` or `<yap-speak>...</yap-speak>` or `<yap-cap>...</yap-cap>`  
- Reason: `markdown-it` treats multi-line HTML as `html_block` and doesn't parse inner markdown

Display math exception:  
- `$$latex$$` can have `yap-speak` on the next line (parser handles this)  
- Blank line required BEFORE `$$block$$` for proper parsing

Example:

$$E=mc^2$$
<yap-speak>E equals m c squared</yap-speak>

Image + caption:  
- No space between image and `yap-cap`: `![](url)<yap-cap>...</yap-cap>`

# Composition Examples

| Pattern | Display | TTS |
|---|---|---|
| `$\alpha$<yap-speak>alpha</yap-speak>` | α | "alpha" |
| `<yap-show>[1, 2]</yap-show>` | [1, 2] | (silent) |
| `<yap-show>(Smith)</yap-show><yap-speak>Smith</yap-speak>` | (Smith) | "Smith" |
| `<yap-cap>Fig 1: $\beta$<yap-speak>beta</yap-speak> <yap-show>[3]</yap-show></yap-cap>` | Fig 1: β [3] | "Fig 1: beta" |

# What Parser Handles Gracefully

- Unclosed tags → treated as text, no crash  
- Empty tags → valid, contribute nothing  
- Unknown tags → passed through as HTML

# What Parser Cannot Handle

- Tags split across lines → becomes `html_block`, inner content not parsed
- Deeply nested same tags → undefined behavior (treat as text)
- **yap-tags inside container elements** (links, strong, em) → semantics ignored, content appears in both display AND TTS. The recursive HTML/TTS extractors don't track yap-tag state. See `TestKnownLimitations` in test_parser_v2.py.


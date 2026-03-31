---
status: done
refs: [ee48a23, 71cc7d8]
---

# Map defuddle semantic callout types to yapit colors

## Context

Defuddle 0.14.0 (published on npm, we're on 0.13.0) introduced callout
standardization (#185). It converts callout/alert elements from various HTML
sources into Obsidian-style markdown callouts: `> [!type] Title`.

Our transformer (`_extract_callout_info` in `transformer.py:1300`) currently
only accepts color-based types: BLUE, GREEN, PURPLE, RED, YELLOW, TEAL, GRAY.
Any unrecognized type returns `None` → callout is treated as a plain blockquote,
losing the visual distinction.

When we upgrade defuddle, its callout types will flow through the same
`parse_markdown → DocumentTransformer.transform` pipeline as LLM-extracted
markdown — and get silently dropped.

## Defuddle callout types

Defuddle standardizes from four sources (`src/elements/callouts.ts`), each
emitting different `data-callout` values that become the `[!type]`:

| Source | Types emitted |
|---|---|
| GitHub markdown alerts (`div.markdown-alert`) | `note`, `tip`, `important`, `warning`, `caution` |
| Obsidian Publish (`div.callout[data-callout]`) | pass-through (any string) |
| Callout asides (`aside.callout-*`) | from class name, e.g. `tip`, `info` |
| Bootstrap alerts (`div.alert.alert-*`) | `primary`, `secondary`, `success`, `danger`, `warning`, `info`, `light`, `dark` |

All types are lowercase in defuddle output. Our parser uppercases them before
the color check (`callout_type = match.group(1).upper()`), so casing isn't the
issue — the types simply aren't in our valid set.

## Proposed mapping

Add a `CALLOUT_TYPE_MAP` dict in the transformer that maps semantic types to
our color palette. Types already in the valid colors set pass through unchanged.
Unknown types default to BLUE (matching Obsidian's behavior — unknown types
render as `note`).

Mapping derived from Obsidian's actual computed `--callout-color` CSS values:

```
Obsidian RGB             Obsidian types                          Our color
─────────────────────────────────────────────────────────────────────────────
rgb(2, 122, 255)    →    note, info, todo                    →  BLUE
rgb(83, 223, 221)   →    abstract/summary/tldr, tip/hint/important  →  TEAL
rgb(68, 207, 110)   →    success/check/done                  →  GREEN
rgb(233, 151, 63)   →    question/help/faq, warning/caution/attention  →  YELLOW
rgb(251, 70, 76)    →    failure/fail/missing, danger/error, bug  →  RED
rgb(168, 130, 255)  →    example                             →  PURPLE
rgb(158, 158, 158)  →    quote/cite                          →  GRAY
```

Full lookup table for the code:

```
note       → BLUE       info       → BLUE       todo       → BLUE
abstract   → TEAL       summary    → TEAL       tldr       → TEAL
tip        → TEAL       hint       → TEAL       important  → TEAL
success    → GREEN      check      → GREEN      done       → GREEN
question   → YELLOW     help       → YELLOW     faq        → YELLOW
warning    → YELLOW     caution    → YELLOW     attention  → YELLOW
failure    → RED        fail       → RED        missing    → RED
danger     → RED        error      → RED        bug        → RED
example    → PURPLE
quote      → GRAY       cite       → GRAY

# Bootstrap alert types (not in Obsidian)
primary    → BLUE       secondary  → GRAY
light      → GRAY       dark       → GRAY

# Unknown types → BLUE (matches Obsidian default)
```

The Obsidian pass-through case means literally any string could appear. Rather
than enumerating every possible type, use the map for known types and fall back
to BLUE for unknowns. This way callouts are never silently dropped.

## Changes needed

1. **`transformer.py`** — In `_extract_callout_info`:
   - Replace the `valid_colors` rejection gate with a mapping step
   - After `.upper()`, check `CALLOUT_TYPE_MAP.get(type, None)` → if found, use
     mapped color; else check if it's already a valid color; else default to GRAY
   - Preserve the title from defuddle's output (it already generates titles like
     "Note", "Warning", etc.)

2. **Unit tests** — Add cases for:
   - `> [!note] Some note` → BLUE callout
   - `> [!warning] Watch out` → YELLOW callout
   - `> [!danger]` (no title) → RED callout with title "Danger"
   - `> [!unknowntype] Foo` → BLUE callout (fallback, matches Obsidian default)
   - Existing color types still work unchanged

3. **Defuddle upgrade** — Bump `docker/defuddle/package.json` from 0.13.0 to
   0.14.0 (or later). Review the full changelog for other changes that may
   affect our pipeline (footnote improvements, BBcode extraction, pipeline
   refactor).

4. **Extraction prompt** — No changes needed. The LLM path continues to use
   COLOR types directly. The mapping only applies to types that aren't already
   valid colors.

## Done when

- Defuddle upgraded to >=0.14.0
- Semantic callout types from defuddle markdown render as colored callouts in
  the frontend (not plain blockquotes)
- Existing LLM-extracted callouts with COLOR types still work
- Unknown callout types default to BLUE instead of being rejected

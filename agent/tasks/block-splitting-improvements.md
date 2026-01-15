---
status: active
started: 2026-01-03
---

# Task: Block Splitting Improvements

## Problem

Sentences split mid-phrase unnaturally, hurting TTS quality:
```
"...we notice a steady rise in the amount of computation [SPLIT] taking place."
```

Also: lists weren't split at all, creating huge 500+ char audio blocks.

## Branch Status

**Branch:** `feat/block-splitting-improvements`

**Implemented:**
- Smarter splitting algorithm with three params: `max_block_chars`, `soft_limit_mult`, `min_chunk_size`
- Split priority: sentence boundaries → clause separators (`,—:;`) → word boundaries
- List items now get individual `audio_block_idx` (container has none)
- Interactive visualization tool: `scripts/block_viz_server.py`

**Remaining:**
- [x] Fix math handling bug (inline math lost during splitting)
- [ ] Parameter tuning via systematic analysis
- [ ] Add env vars to Settings class
- [ ] Wire params to `transform_to_document` calls
- [ ] Validate with real TTS playback

## Bug: Inline Math Lost During Splitting

**Discovered:** 2026-01-15

When paragraphs with inline math (`$...$`) get split, the math disappears from HTML output.

**Root cause:** `InlineContent` AST doesn't model `math_inline`:
1. `_transform_inline_node` doesn't handle `math_inline` → becomes `TextContent`
2. `_slice_inline_node` doesn't recognize math → returns `[]` (dropped)
3. `_render_inline_content_html` has no math case → can't render

**Fix:**
- Add `MathInlineContent` to `InlineContent` union in `models.py`
- Handle `math_inline` in `_transform_inline_node` → create `MathInlineContent`
- Handle in `_get_inline_length` → return 0 (math doesn't count toward block size)
- Handle in `_slice_inline_node` → atomic (include fully or skip)
- Handle in `_render_inline_content_html` → `<span class="math-inline">...</span>`

## Parameter Analysis Plan

### Parameter Space (64 combinations)
```
max_block_chars: [150, 200, 250, 300]
soft_limit_mult: [1.0, 1.3, 1.7, 2.0]
min_chunk_size:  [20, 40, 60, 80]
```

### Constraints
- **Latency safe zone:** median ~200-250 chars, absolute max <350
- Prefetch algorithm: 4 blocks before playback starts
- Start higher (better splitting), easy to shrink if latency issues

### Evaluation Approach
1. Run all parameter combinations on test corpus
2. Collect stats: block count, median, p95, max, size distribution
3. **Qualitative analysis**: Read actual splits, judge if they'd sound natural spoken aloud
4. Identify which combinations produce "reasonable" splitting across all text types

### Test Corpus
`scripts/block-splitter-test-corpus.md` — ~5 pages of varied content:
1. Dense academic prose (long sentences, multiple clauses)
2. Conversational web article (shorter, casual)
3. Technical documentation (lists, code refs)
4. Mixed list content (long list items)
5. Narrative with dialogue (quotes, pauses)
6. Dense technical explanation
7. Parenthetical/quote heavy

## Key Questions

1. At what `max_block_chars` do we catch "almost all" cases with reasonable splits?
2. How do `soft_limit_mult` and `min_chunk_size` interact with max size?
3. What's the actual max block size produced for each config?
4. Which configs keep median ~200 while avoiding forced word-boundary splits?

## Sources

- `yapit/gateway/processors/markdown/transformer.py` — splitting logic
- `yapit/gateway/processors/markdown/models.py` — block/inline content models
- `scripts/block_viz_server.py` — interactive visualization
- [[document-processing]] — how blocks flow through the system

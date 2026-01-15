---
status: done
started: 2026-01-03
completed: 2026-01-15
pr: https://github.com/yapit-tts/yapit/pull/56
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
- [x] Parameter tuning via systematic analysis
- [x] Add env vars to Settings class
- [x] Wire params to `transform_to_document` calls
- [ ] Validate with real TTS playback

## Bug: Inline Math Lost During Splitting (FIXED)

**Discovered:** 2026-01-15 | **Fixed:** `c695f19`

When paragraphs with inline math (`$...$`) get split, the math disappeared from HTML output.

**Root cause:** `InlineContent` AST didn't model `math_inline` — fell through to TextContent, then dropped during slicing.

**Fix:** Added `MathInlineContent` to models and handled in all transformer methods.

## Feature: Alt Text for Math & Images

**Syntax:**
- Inline math: `$\alpha${alpha}` — LaTeX rendered, "alpha" spoken by TTS
- Display math: `$$E=mc^2$$\n{E equals m c squared}` — alt on next line
- Images: `![alt](url){caption}` — both alt and caption spoken by TTS

**Implementation (backend done):**
- Models: `MathInlineContent.alt`, `MathBlock.alt`, `ImageBlock.caption`
- Transformer: AST post-processing extracts `{...}` annotations
- `audio_block_idx` assigned when alt/caption present (empty = no audio)

**Pending:**
- [ ] Unit tests for annotation extraction
- [ ] Frontend: render image captions, handle new model fields

See [[2026-01-15-block-splitting-math-alt-tests-frontend]] for handoff.

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

## Parameter Analysis Results (2026-01-15)

Ran `scripts/block_splitter_benchmark.py` on test corpus (64 combinations).

### Bug Found & Fixed

Word-boundary fallback didn't respect `min_chunk_size`, creating orphans like "domains." (8 chars). Fixed by absorbing orphans under `min_chunk_size` into previous chunk.

### Observations

- `min_chunk_size` had minimal effect before the fix; now properly prevents tiny orphans
- 40/64 configs stayed under 350-char max (latency safe zone)
- Higher `soft_limit_mult` keeps complete sentences/quotes together but increases max block size

### Tested Configs

| Config | Blocks | Median | Max | Notes |
|--------|--------|--------|-----|-------|
| max=200, soft=1.3 | 61 | 139 | 239 | Conservative, more fragments |
| max=250, soft=1.0 | 56 | 146 | 247 | Middle ground |
| max=250, soft=1.3 | 53 | 157 | 315 | Keeps quotes/thoughts together |

### Selected: max=250, soft=1.3, min_chunk=40

Tradeoff: slightly longer blocks (up to ~315) but better thought coherence. Quoted passages and clause pairs stay together. Still under 350 safe zone.

## Sources

- `yapit/gateway/processors/markdown/transformer.py` — splitting logic
- `yapit/gateway/processors/markdown/models.py` — block/inline content models
- `scripts/block_viz_server.py` — interactive visualization
- `scripts/block_splitter_benchmark.py` — parameter benchmarking
- [[document-processing]] — how blocks flow through the system

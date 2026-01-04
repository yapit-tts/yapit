---
status: active
started: 2026-01-03
---

# Task: Block Splitting Improvements

## Problem

Sentences were being split mid-phrase unnaturally:
```
"...we notice a steady rise in the amount of computation [SPLIT] taking place."
```

## What Was Done

### 1. Improved Splitting Algorithm (`transformer.py`)

**Three configurable parameters:**
- `max_block_chars` - target max block size (default 150)
- `soft_limit_mult` - how much overage allowed to keep sentences whole (default 1.2)
- `min_chunk_size` - minimum chunk size to avoid tiny orphans (default 30)

**Algorithm:**
1. Split at sentence boundaries (`.!?`) first
2. If sentence ≤ `max × soft_mult`, keep it whole
3. If sentence exceeds soft limit, split at pause points: `,` `—` `:` `;`
4. Pause regex includes optional closing quotes: `[,—:;]["')\]\u201c\u201d\u2018\u2019]?`
5. `min_chunk_size` prevents tiny orphan chunks by preferring pause points that leave enough remaining
6. Fallback: word boundary split if no good pause point

### 2. List Items Now Separate Audio Blocks

- Each list item gets its own `audio_block_idx`
- `ListBlock` is now a container (like `BlockquoteBlock`)
- Prevents 500+ char lists from being single audio blocks

### 3. Interactive Visualization Tool

`scripts/block_viz_server.py` - FastAPI server with sliders for all parameters, real-time updates.

```bash
python scripts/block_viz_server.py whatisintelligencechap1.md
```

## Findings from Testing

Best results with `whatisintelligencechap1.md` (156K chars):
- `max_block_chars=200`, `soft_limit_mult=1.5`, `min_chunk_size=80`
- Most sentences stay coherent, avg block size ~126 chars
- Even with 300 char soft limit, most blocks stay 150-160 chars (natural sentence lengths)
- Reduces block count by ~200 blocks compared to max=150 (1130 → 915)
- Potential latency benefit from fewer blocks (less hop overhead) - needs validation

## Still TODO

### Before Merging
- [ ] Add settings to config (`MAX_BLOCK_CHARS`, `SOFT_LIMIT_MULT`, `MIN_CHUNK_SIZE`)
- [ ] Test with actual TTS playback to validate quality improvement
- [ ] Commit to feature branch

### Follow-up (depends on [[monitoring-observability-logging]])
- [ ] Measure latency impact of larger blocks (150 vs 200 vs 250)
- [ ] Validate no buffering issues with WebGPU
- [ ] Data-driven tuning of parameters

### Edge Cases (low priority)
- [ ] Very long headings (malformed docs) - currently not split
- [ ] Very long list items - currently not split within item

## Sources

- `yapit/gateway/processors/markdown/transformer.py` - main splitting logic
- `yapit/gateway/processors/markdown/models.py` - ListItem now has audio_block_idx
- `scripts/block_viz_server.py` - interactive visualization
- `whatisintelligencechap1.md` - test document (156K chars)

## Handoff

Algorithm is implemented and working. Next agent should:
1. Add the three params to Settings class (with defaults from `.env`)
2. Wire them through to where `transform_to_document` is called
3. Test with real TTS playback
4. Consider doing monitoring task first to get baseline metrics

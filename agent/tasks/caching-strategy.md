---
status: done
started: 2026-01-03
completed: 2026-01-15
commit: 11db22e
---

# Task: Caching Strategy

## Cache Eviction

LRU + TTL mechanism not implemented yet. Low priority for beta (small user count), needed before scale.

## What We Cache

- Audio cache (ephemeral, not too large - Hetzner SSD is fine)
- Transformed documents (just markdown, even smaller)
- OCR results — stored as part of document model in DB

## OCR Caching Thoughts

Since we store OCR'd text in the document model, we already have a cache. Need to ensure we don't re-OCR something already processed.

Considerations:
- Track OCR model version per document (currently just "mistral-ocr" which auto-updates)
- If Mistral releases better model, could evict/relax check with version tracking
- Add env var for OCR model version

## Questions to Answer

- What's actually implemented for caching OCR results?
- What disk size do we have available? Is it even an issue at all since we only store text?


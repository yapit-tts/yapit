---
status: done
started: 2026-01-24
completed: 2026-01-27
---

# Task: Markxiv Free Tier Improvements

Rules-based cleanup for markxiv output to improve free tier arXiv paper experience.

## Implemented

All cleanup happens in `cleanup_markxiv_markdown()` in `yapit/gateway/document/markxiv.py`:

| Pattern | Action |
|---------|--------|
| Header anchors `# Title {#sec:...}` | Strip anchor, keep header |
| Standalone anchors `{#fig:...}` | Delete |
| Citations `[@author_year]` | Delete (visual clutter) |
| Reference attrs `{reference-type="..." reference="..."}` | Delete |
| Orphan label refs `[fig:X]`, `[tab:Y]` | Delete (no images in free tier) |
| Raw URLs `https://...` | Wrap in `<yap-show>[url](url)</yap-show>` (clickable but silent) |

Also fixed a bug where `<yap-show>` content was lost during paragraph splitting — added `ShowContent` AST node type to preserve display-only content through the slicing process.

## Sources

- `yapit/gateway/document/markxiv.py` — cleanup implementation
- `yapit/gateway/markdown/models.py` — ShowContent model
- `yapit/gateway/markdown/transformer.py` — ShowContent handling
- [[2026-01-23-markxiv-arxiv-integration]] — parent task

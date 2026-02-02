---
status: done
started: 2026-01-03
---

# Task: Vim-Style Keybindings

Keyboard controls for playback.

## Keybindings to Consider

- **hjkl** — navigation (h/l for speed? j/k for skip blocks?)
- **Arrow keys** — skip forward/back, maybe scroll
- **Space** — play/pause (already works)
- **f** — find/search in document (or rather find a document itself)? (or ctrl+/ as standard)

## Design Questions

- Where do settings live? In playback settings dialog? Separate keybindings dialog?
- Should be toggleable (some users might not want vim bindings) (but non-goal to make keys configurable?)
- Think holistically about settings architecture — OCR batch mode, vim keybindings, etc. all need a home

## Scope

Probably don't need to build emacs — hjkl + arrows + space is likely enough. Don't overcomplicate.

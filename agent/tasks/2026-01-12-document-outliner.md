---
status: active
started: 2026-01-12
---

# Task: Document Outliner / Chapter Navigation

## Intent

Large documents (books, long papers) produce unwieldy playback experiences. A 30-hour playbar is essentially useless for navigation. Add an outline-based view that lets users collapse/expand sections based on heading structure, with the playbar scoped to the currently expanded section.

## Core Concept

**Outliner UI**: Right sidebar (similar to left document sidebar, hidden by default, expandable) showing document structure based on headings. Each heading is collapsible:

```
▼ Part I: Foundations
  ▼ Chapter 1: Introduction
      [content blocks...]
  ▶ Chapter 2: Background      ← collapsed
  ▶ Chapter 3: Methods         ← collapsed
▶ Part II: Applications        ← collapsed
```

**Playbar scoping**: When viewing a collapsed section, playbar shows only that section's duration and progress. Not the full 30 hours - just the 45 minutes of Chapter 3 you're currently in.

**Default expansion**: Auto-expand the section containing the current playback block index (synced from backend). Everything else collapsed.

**Pure frontend**: Backend unchanged. One document, one block list. Frontend filters/groups blocks by heading structure from `structured_content`.

## Trigger Condition

Only show outliner for documents that would benefit:
- Has headings in structured_content
- Maybe: more than X blocks (e.g., 50+)
- Or: total duration above threshold

## The Heading Consistency Problem

If pages are processed independently (parallel VLM extraction), heading levels might be inconsistent across pages. Page 10's "Chapter 1" might be H2, page 50's "Chapter 2" might be H1.

### Approaches - What to Try

**1. Test first, see how bad it is**
VLM sees the visual styling (font size, bold, centering). Might be more consistent than we fear. Test before over-engineering.

**2. Constrained heading levels in prompt**
Instead of "be consistent" (useless without context), constrain to fewer levels: "Only use H1 for major divisions, H3 for subdivisions." Forces coarser granularity but more consistency.

**3. Post-processing normalization**
After parallel extraction completes, analyze all headings:
- Detect patterns: "Chapter N" text → normalize to same level
- Heuristics based on heading text patterns
- Doesn't break parallelism, just adds cleanup pass

### Approaches - Rejected

**TOC-first extraction**: Extract table of contents first, use as reference. Rejected - detecting/parsing TOCs reliably is its own problem.

**Naive "be consistent" prompting**: Telling VLM to be consistent without context doesn't help - it has no knowledge of other pages.

**Injecting prior headers into prompt**: Would require sequential processing or wave-based batching, breaks parallelism speedups.

## Implementation Notes

- Uses existing `structured_content` heading blocks with levels
- Build chapter index: `[{title, level, startBlockIdx, endBlockIdx}, ...]`
- Nested collapse/expand based on heading hierarchy
- Playbar recalculates duration for visible block range
- Block index sync from backend determines which section to auto-expand

## Done When

- [ ] Right sidebar outliner UI (hidden by default, expandable)
- [ ] Heading hierarchy parsed from structured_content
- [ ] Collapse/expand sections
- [ ] Playbar scoped to expanded section
- [ ] Auto-expand section containing current playback position
- [ ] Only shown for documents meeting trigger condition

## Design

TBD - general concept is right sidebar similar to left document sidebar.

## Related: Large Document Performance

Very large documents (30-hour book) can crash browser tabs - too many DOM elements, memory pressure, etc.

The outliner helps by collapsing sections (fewer rendered blocks), but may also need:
- **Virtualization**: Only render blocks currently in viewport (react-window, etc.)
- **Pagination**: Load blocks in chunks as user scrolls
- **Lazy rendering**: Collapsed sections don't render their content until expanded

The outliner and performance fixes work together - outliner for navigation UX, virtualization/pagination for not killing the browser.

## Dependencies

May need to address heading consistency in extraction first, depending on test results.

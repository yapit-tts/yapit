---
status: done
started: 2026-01-12
completed: 2026-01-27
pr: https://github.com/yapit-tts/yapit/pull/63
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

### Solution: Flat Outliner with Binary Heading Classification

**Key insight:** We don't need deep nesting for navigation. A 30-hour book with 20 chapters just needs chapter-level collapse, not Part > Chapter > Section > Subsection hierarchy.

**Approach:**
- Only H1/H2 ("major headings") become collapsible sections in the outliner
- Everything between two major headings = that section's content
- H3+ are styled headings within sections, but don't create nesting
- Binary classification (major vs minor) is much more robust than multi-level consistency

**Prompt guidance (needs to be added to extraction prompt):**
- "Use H2 for major divisions (chapters, parts). Use H3+ for subdivisions."
- VLM still uses H3, H4, etc. for visual styling — we just don't rely on them for outliner structure

**For TOC rendering:**
- Flat list of links: `- [Chapter 1](#chapter-1)`
- No nesting needed, no level detection needed
- Anchors work regardless of actual heading level (`[](#header)` links work for any Hn)

This sidesteps the consistency problem entirely — we only need VLM to consistently identify "is this a major division?" rather than maintaining perfect H1/H2/H3/H4 hierarchy across pages.

### Approaches - Rejected

**Deep nesting based on heading levels**: Too brittle — requires consistent H1/H2/H3/H4 assignment across independently-processed pages.

**TOC-first extraction**: Extract table of contents first, use as reference. Rejected - detecting/parsing TOCs reliably is its own problem.

**Naive "be consistent" prompting**: Telling VLM to be consistent without context doesn't help - it has no knowledge of other pages.

**Injecting prior headers into prompt**: Would require sequential processing or wave-based batching, breaks parallelism speedups.

**Post-processing normalization via regex/heuristics**: Brittle — not all documents use numbered sections or consistent text patterns.

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

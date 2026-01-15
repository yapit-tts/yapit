---
status: active
started: 2026-01-12
---

# Task: Tips Page Showcase

## Intent

Add a curated showcase of example documents to the Tips page (`/tips`). Let new users see what Yapit can do with real documents before processing their own.

## Background: What We Considered & Rejected

### Public Library (rejected)

Idea: A browsable library of all public documents.

Rejected because:
- Just titles = useless, need visual previews = complexity
- Quality control, moderation, spam concerns
- Drifts toward social platform territory (user profiles, etc.)
- "One thing well" - this isn't that thing

### Opt-in Public Listing (rejected)

Idea: Separate `is_public` (shareable via link) from `is_listed` (appears in public library).

Rejected because:
- Same problems as above, just with an extra toggle
- Still need to solve "what do you show" problem

### arXiv Integration (rejected)

Idea: Dedicated `/arxiv` page showing converted arXiv papers, using arXiv IDs as URLs (`yapit.md/arxiv/2301.12345`).

Appealing because:
- Built-in metadata (title, authors, abstract)
- No copyright issues (open access)
- SEO potential for academic audience
- Natural deduplication by paper ID

Rejected because:
- Scope creep - special-casing one source
- Metadata fetching complexity
- "Dancing on too many weddings" (idiom: spreading too thin)

### Separate Showcase Website (maybe future)

Idea: A second website solely for collecting/showcasing Yapit documents, linking back to yapit.md.

Not rejected, just deferred. Could be a simple static site with curated links.

## What We're Doing Instead

Simple curated showcase on the existing Tips page:
- Hand-pick 3-5 interesting documents
- Process them in admin account, mark as public
- Hardcode their IDs on the Tips page
- Zero new infrastructure

## Done When

- [ ] Tips page has a "Sample Documents" section
- [ ] 3-5 showcase documents selected and processed
- [ ] Cards/links to showcase documents on Tips page

## Design

TBD - no design decisions made yet, just the general approach.

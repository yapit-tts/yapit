---
status: done
started: 2026-02-09
---

# Task: yapit.md/URL Catch-All Routing

## Intent

Allow `yapit.md/example.com/article` to create a document from the URL and land on playback. Frontend-only change using existing backend helpers.

Extracted from workstream 3 of [[2026-02-02-website-experience-improvements]].

## Implementation

Add a catch-all route in `frontend/src/routes/AppRoutes.tsx` that:

1. Matches `/*` paths that look like URLs (contain a `.` TLD after the first segment)
2. Extracts the URL from the path (everything after the leading `/`)
3. For websites: calls existing `POST /v1/documents/website` endpoint, redirects to `/listen/:documentId`
4. For PDFs/documents: calls `POST /v1/documents/prepare`, shows the MetadataBanner flow (or redirects to the main input page pre-filled)
5. Falls through to 404 for non-URL paths

Must be placed before the existing `<Route path="*" element={<NotFoundPage />} />`.

## Key Files

- MUST READ: `frontend/src/routes/AppRoutes.tsx` -- existing route definitions
- MUST READ: `frontend/src/components/unifiedInput.tsx` -- URL input flow, `handleUrlContent()`, auto-creation for websites
- Reference: `frontend/src/lib/api.ts` -- API client methods

## Done When

- [ ] `yapit.md/arxiv.org/abs/1706.03762` creates doc and lands on playback
- [ ] `yapit.md/example.com/blog-post` works for websites
- [ ] Non-URL paths (e.g., `/listen/123`) still route normally
- [ ] Invalid/malformed URLs show error or fall through to 404

---
status: done
type: debugging
started: 2025-12-30
completed: 2026-01-01
---

# Task: External Image URLs Broken in Converted Webpages

## Problem

When converting webpages, relative image URLs (e.g., `/images/foo.png`) were rendered relative to Yapit's domain instead of the source webpage's domain.

## Root Cause

MarkItDown converts HTML to markdown but preserves URLs as-is. Relative paths like `/images/foo.png` stay relative. When the frontend renders `<img src="/images/foo.png">`, the browser resolves it to `yapit.app/images/foo.png`.

## Solution

Added `_resolve_relative_urls()` in `documents.py` that post-processes markdown after MarkItDown conversion:

1. **URL resolution**: Uses `urllib.parse.urljoin` to resolve relative URLs against source webpage URL
2. **Space encoding**: Encodes spaces as `%20` since markdown parsers don't handle unencoded spaces
3. **Same-page anchors**: Converts links pointing to same page (both full URLs like `https://site.com/page/#section` and relative like `/page/#section`) to just `#section`

Preserves:
- Anchor links: `#section` (stays as-is)
- Already absolute URLs to different pages: `https://...`
- Data URIs: `data:...`

## Additional Fixes

- **Video embedding**: Frontend detects video links (.mp4, .webm, .mov, .ogg) and replaces with `<video>` elements
- **Image sizing**: Added `max-height: 24rem`, centered with `margin: auto`
- **External link arrows**: Consistent SVG icon instead of font-dependent Unicode character
- **Accented heading slugs**: Normalize accented chars (é → e) so links like `#elan-vital` match heading "Élan Vital"

## Files Changed

- `yapit/gateway/api/v1/documents.py` - `_resolve_relative_urls()` with same-page anchor detection
- `frontend/src/components/structuredDocument.tsx` - video embedding, image styling, arrow icon, slug normalization

## Gotchas

**Firefox DOM timing**: useEffect runs before Firefox paints the DOM. When querying DOM elements set via `dangerouslySetInnerHTML`, wrap in `setTimeout(..., 0)` to defer to next tick. Chromium paints synchronously, Firefox doesn't. See `0962a6d` for fix.

## Commits

- `0607b8f` - Initial URL resolution fix
- `ba03e60` - Same-page anchors and accented slug fix
- `0962a6d` - Firefox video embed timing fix

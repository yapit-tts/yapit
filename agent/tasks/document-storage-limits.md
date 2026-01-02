---
status: pending
type: implementation
---

# Task: Document Storage Limits

## Goal

Add platform-wide sanity limits for document storage to prevent abuse and unbounded growth. These are not tier-differentiated - they apply to all users (including free/guest).

## Constraints / Design Decisions

1. **Not billing-related** — These are platform safety limits, not subscription features
2. **Apply to all tiers** — Same limits for free and paid users
3. **Graceful handling** — Auto-eviction for count limits, not hard blocks

## Proposed Limits

- **Document size**: ~100MB max per document (already exists as `document_max_download_size`, but needs enforcement on uploads)
- **Document count**: ~5k per user, auto-evict oldest when exceeded

## Current State

- `document_max_download_size = 100MB` in config.py
- Applied to URL downloads in `_download_document()`
- Markitdown processor uses it as `max_file_size`
- Direct file uploads (`/prepare/upload`) don't explicitly check size before reading into memory
- No document count limits exist

## Next Steps

1. Audit where size limit is/isn't enforced (URL download vs direct upload)
2. Add explicit size check to file upload endpoint before reading
3. Implement document count limit with auto-eviction:
   - When creating new document, check count
   - If over limit, delete oldest documents (by created date)
   - Or: block creation with clear error message
4. Add config settings: `document_max_count_per_user`

## Open Questions

1. Auto-eviction vs hard block when hitting document count limit?
   - Auto-eviction: seamless UX, but users might lose documents unknowingly
   - Hard block: requires user action, but explicit

2. Should we notify users when approaching limits?

---

## Notes / Findings

Related: Browser TTS audio is stored to backend (BlockVariant cache), so storage isn't zero for free users. But audio cache can be evicted independently of documents.

---
status: active
started: 2026-01-12
---

# Task: Document Sharing via Clone/Import

## Intent

Enable users to share documents by link. When someone clicks a share link, the document is **cloned** into their account (or guest account). This allows:

- Sharing already-OCRed papers (recipient saves OCR costs)
- Promotional sample documents on website
- Friends sharing with friends who can't afford premium

The clone is independent - owner pays nothing ongoing, viewer uses their own quota for TTS.

## Assumptions

- Share = clone, not "access my document"
- Viewer needs their own account/quota for server TTS (browser TTS always available)
- Already-cloned documents persist even if owner toggles off sharing
- UUIDs are sufficiently unguessable (no need for separate share tokens)

## Design Decisions

### Data Model

```python
class Document(SQLModel, table=True):
    # ... existing fields ...
    is_public: bool = Field(default=False)
```

Simple toggle. No share tokens needed - UUIDs are practically unguessable.

### URL Strategy: Unified `/listen/{id}`

Reuse the existing `/listen/{id}` URL rather than a separate `/share/{id}`:

- **Owner visits**: Normal playback
- **Non-owner visits public doc**: Import preview → "Add to Library" → clone
- **Non-owner visits private doc**: "Document not found" (don't leak existence)

Benefits:
- Copy URL from address bar = share URL
- No separate "get share link" action needed
- Power-user friendly

### What Gets Cloned

| Field | Cloned | Notes |
|-------|--------|-------|
| `title` | ✓ | |
| `original_text` | ✓ | |
| `structured_content` | ✓ | Preserves OCR/extraction work |
| `extraction_method` | ✓ | |
| `metadata_dict` | ✓ | Original source info |
| `blocks` | ✓ | Block records (text, idx, est_duration) |
| `user_id` | ✗ | Set to viewer's ID |
| `block_variants` | ✗ | TTS cache - viewer generates own |
| `last_block_idx`, `last_played_at` | ✗ | Playback position is viewer-specific |

### API Design

```
GET /v1/documents/{id}/public
  → No auth required
  → Returns: title, block_count, source_url, preview text (first N chars?)
  → 404 if not public or doesn't exist

POST /v1/documents/{id}/import
  → Requires auth (can be anonymous user)
  → Clones document to authenticated user's account
  → Returns new document ID
```

### User Setting: Default Shareable

Add user preference: "Make new documents shareable by default"

- Stored in `UserPreferences` table
- When creating document, if setting enabled → `is_public=True`
- Power users who frequently share can enable this

## Frontend Design

### Sharing Toggle (Owner's View)

**Location:** Sidebar three-dot menu (where Rename/Delete already live)

**UI:** Stateful menu item, not a toggle widget:

```
When private:
┌─────────────┐
│ Rename      │
│ Share...    │  ← neutral state
│ Delete      │
└─────────────┘

After clicking "Share...":
┌──────────────────────┐
│ Rename               │
│ ✓ Shared             │  ← green checkmark
│   Link copied!       │  ← subtle confirmation
│ Delete               │
└──────────────────────┘
```

**Behavior:**
- Click "Share..." → toggle to public, auto-copy URL to clipboard, show "Link copied!"
- Click "✓ Shared" → toggle back to private
- No popup/dialog needed

### Non-Owner Viewing Public Document

**Access model:** Ephemeral access with optional save
- Full document loads immediately, fully playable (uses viewer's TTS quota)
- Document is NOT cloned until user explicitly saves it
- No sidebar entry, no saved position until added to library

**"Add to Library" banner:**

Position: Inline below header, above document content (not floating/overlaying)

```
┌─────────────────────────────────────────────────────┐
│  Document Title                    [Copy][Down][...]│
├─────────────────────────────────────────────────────┤
│  📥 Shared document          [Add to Library]   [×] │
├─────────────────────────────────────────────────────┤
│  Document content...                                │
```

**Behavior:**
- Shows when non-owner visits public doc
- [Add to Library] → clones doc to their account, redirects to their copy
- [×] → dismisses banner (can still use doc ephemerally)
- Refresh → banner reappears (no persistence for non-owner docs)
- Copy/Download buttons still work (viewing the content is fine)

### User Preferences

Two new preferences in `UserPreferences`:

**`auto_import_shared_documents: bool = False`**
- If true: skip banner, auto-clone shared docs on page load
- Power users who frequently receive shared links

**`default_documents_public: bool = False`**
- If true: new documents are created with `is_public=True`
- Power users who frequently share their documents

Both need UI toggles in the settings/preferences area.

## Edge Cases

| Case | Behavior |
|------|----------|
| Import same doc twice | Allow - user might want multiple copies |
| Owner toggles off after import | Existing clones persist, new imports blocked |
| Guest imports, then signs up | Document transfers via existing claim flow |
| User visits their own public doc | Normal playback (not import flow) |

## Done When

**Backend:**
- [ ] `is_public` field added to Document model + migration
- [ ] `GET /v1/documents/{id}/public` endpoint (no auth) - returns full document data if public
- [ ] `POST /v1/documents/{id}/import` endpoint - clones doc to authenticated user
- [ ] `PATCH /v1/documents/{id}` extended to support `is_public` toggle

**Frontend:**
- [ ] Sidebar menu: "Share..." / "✓ Shared" stateful item with auto-copy
- [ ] PlaybackPage: handle 403 → fetch public endpoint → show banner if public
- [ ] "Add to Library" banner component (dismissible, reappears on refresh)
- [ ] Import action: call API, redirect to new doc

**User Preferences:**
- [ ] `auto_import_shared_documents` preference + UI toggle
- [ ] `default_documents_public` preference + UI toggle

## Sources

**Knowledge files:**
- [[document-processing]] - document structure and what fields exist
- [[auth]] - how auth works, anonymous users

## Considered & Rejected

### Share Tokens

Could generate unique tokens per document for revocable links (`/s/{token}`).

Rejected because:
- UUIDs already unguessable (122 random bits)
- Adds complexity (token generation, storage, lookup)
- Uglier URLs
- Revocation via `is_public=False` achieves same goal

### Separate `/share/{id}` Route

Could have dedicated share route separate from `/listen/{id}`.

Rejected because:
- Less ergonomic (can't just copy URL)
- Requires explicit "get share link" action
- More cognitive load for users

### Access-Based Sharing (Owner's Quota)

Could let viewers access owner's document directly (no clone), with TTS using owner's quota.

Rejected because:
- Risk of draining owner's credits
- More complex permissions model
- Clone approach has zero marginal cost to owner

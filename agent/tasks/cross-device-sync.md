---
status: done
type: implementation
started: 2026-01-05
---

# Task: Cross-Device Sync

Parent: [[soft-launch-blockers]]

## Intent

Sync key user state across devices so switching from laptop to phone preserves progress.

**Sync:** Playback position per document, pinned/favorite voices
**Don't sync:** Selected voice, speed, scroll mode, OCR toggle (device-specific preferences)

## What to Sync

| Setting | Sync? | Rationale |
|---------|-------|-----------|
| Playback position (block index) | ✅ Yes | Resume where you left off |
| Pinned/favorite voices | ✅ Yes | Curated list shouldn't differ |
| Selected voice | ❌ No | Might prefer different voice per device |
| Speed | ❌ No | Might prefer different speed (commute vs desk) |
| Scroll/tracking mode | ❌ No | Device-specific UX |
| OCR batch toggle | ❌ No | Device-specific |

## Schema Changes

### On Document Model

```python
# In domain_models.py, Document class:
last_block_idx: int | None = Field(default=None)
last_played_at: datetime | None = Field(default=None)
```

### New UserPreferences Table

```python
class UserPreferences(SQLModel, table=True):
    __tablename__ = "userpreferences"

    user_id: str = Field(primary_key=True)
    pinned_voices: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    created: datetime = Field(default_factory=datetime.utcnow)
    updated: datetime = Field(default_factory=datetime.utcnow)
```

## Backend Endpoints

### Update Playback Position

`PATCH /v1/documents/{document_id}/position`

```python
class PositionUpdate(BaseModel):
    block_idx: int

@router.patch("/documents/{document_id}/position")
async def update_position(
    document_id: UUID,
    body: PositionUpdate,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    doc = await get_document_or_404(db, document_id, user.id)
    doc.last_block_idx = body.block_idx
    doc.last_played_at = datetime.utcnow()
    await db.commit()
    return {"ok": True}
```

### Get/Update Pinned Voices

`GET /v1/users/me/preferences`
`PATCH /v1/users/me/preferences`

```python
class PreferencesUpdate(BaseModel):
    pinned_voices: list[str] | None = None

@router.get("/users/me/preferences")
async def get_preferences(user: User = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    prefs = await db.get(UserPreferences, user.id)
    if not prefs:
        return {"pinned_voices": []}
    return {"pinned_voices": prefs.pinned_voices}

@router.patch("/users/me/preferences")
async def update_preferences(
    body: PreferencesUpdate,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    prefs = await db.get(UserPreferences, user.id)
    if not prefs:
        prefs = UserPreferences(user_id=user.id)
        db.add(prefs)

    if body.pinned_voices is not None:
        prefs.pinned_voices = body.pinned_voices
    prefs.updated = datetime.utcnow()

    await db.commit()
    return {"pinned_voices": prefs.pinned_voices}
```

## Frontend Changes

### Sync Playback Position

On block change (not every progress tick):

```typescript
// In playback logic, when block changes:
if (isAuthenticated && documentId) {
  api.patch(`/v1/documents/${documentId}/position`, { block_idx: currentBlock });
}
```

On document load, read `last_block_idx` from document response and restore.

### Sync Pinned Voices

On pin/unpin:

```typescript
// After updating local pinned voices state:
if (isAuthenticated) {
  api.patch('/v1/users/me/preferences', { pinned_voices: pinnedVoices });
}
```

On app load (if authenticated), fetch preferences and merge with localStorage.

## Sources

- `frontend/src/hooks/voiceSelection.ts:90-101` — PINNED_VOICES_KEY localStorage
- `frontend/src/pages/PlaybackPage.tsx:15-38` — playback position localStorage
- `yapit/gateway/domain_models.py:75-120` — Document model

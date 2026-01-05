---
status: active
type: implementation
started: 2026-01-05
---

# Task: Guest to Registered User Conversion

Parent: [[soft-launch-blockers]]

## Intent

When anonymous user signs up, transfer their documents to the new account. Currently anonymous users get `anon-{uuid}` ID, documents have `user_id` pointing to this. On registration, they get a NEW Stack Auth user ID — need to transfer ownership.

## Current Flow

1. **Anonymous ID generation:** `auth.py` creates `anon-{uuid}` prefix
2. **Frontend:** Stores UUID in localStorage (`yapit_anonymous_id`)
3. **API calls:** Send `X-Anonymous-ID` header
4. **Documents:** Created with `user_id = "anon-{uuid}"`

**Gap:** No mechanism to transfer docs from anon → real user.

## Implementation

### Backend: Claim Endpoint

`POST /v1/users/claim-anonymous`

```python
@router.post("/users/claim-anonymous")
async def claim_anonymous_data(
    user: User = Depends(require_auth),  # Real authenticated user
    anon_id: str | None = Header(None, alias="X-Anonymous-ID"),
    db: AsyncSession = Depends(get_db),
):
    if not anon_id or user.is_anonymous:
        return {"claimed": 0}

    anon_user_id = f"anon-{anon_id}"

    # Transfer documents
    doc_result = await db.exec(
        update(Document)
        .where(Document.user_id == anon_user_id)
        .values(user_id=user.id)
    )

    # Transfer filters (if any)
    filter_result = await db.exec(
        update(Filter)
        .where(Filter.user_id == anon_user_id)
        .values(user_id=user.id)
    )

    await db.commit()
    return {"claimed_documents": doc_result.rowcount, "claimed_filters": filter_result.rowcount}
```

### Frontend: Call on First Authenticated Load

In auth context or app initialization:

```typescript
// After successful login/signup
const anonId = localStorage.getItem('yapit_anonymous_id');
if (anonId && isAuthenticated) {
  await api.post('/v1/users/claim-anonymous', null, {
    headers: { 'X-Anonymous-ID': anonId }
  });
  localStorage.removeItem('yapit_anonymous_id');
}
```

## Edge Cases

**Accepted:**
- User has anon docs on device A, registers on device B → docs on A orphaned until they log in on A
- This is fine — they can log in on device A to trigger claim

**Not transferred:**
- UsageLog entries — billing audit, anon users don't have subscriptions anyway

## Sources

- `yapit/gateway/auth.py:13-56` — anonymous ID handling, ANONYMOUS_ID_PREFIX
- `frontend/src/lib/anonymousId.ts` — localStorage functions
- `frontend/src/api.tsx:60-62` — X-Anonymous-ID header

## No Schema Changes

This task doesn't add new columns — just needs the endpoint and frontend call.

---
status: done
type: implementation
started: 2026-01-05
completed: 2026-01-06
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

## Implementation (Done)

Backend: `yapit/gateway/api/v1/users.py:160-185` — `POST /v1/users/claim-anonymous`
- Transfers documents only (filters skipped — anon users can't create them)
- Returns `{ claimed_documents: int }`

Frontend: `frontend/src/api.tsx:96-108`
- Calls claim endpoint after successful auth if localStorage has anonymous ID
- Clears localStorage on success
- Uses `claimAttempted` ref to prevent duplicate calls

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

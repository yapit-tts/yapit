---
status: active
refs:
  - "[[2026-02-21-red-team-security-audit]]"
---

# Server-issued anonymous session tokens

## Intent

`claim-anonymous` transfers all documents from an anonymous session to the authenticated user, but accepts the anonymous ID on blind trust. An attacker who knows someone's anonymous UUID can steal their documents. The server should prove it issued the session before allowing a claim.

## Approach

HMAC-signed tokens. Stateless, no Redis/DB state needed.

**New endpoint:** `POST /v1/users/anonymous-session`
- Server generates UUID, computes `hmac(uuid, settings.anonymous_session_secret)`, returns `{id, token}`
- Rate-limited per IP (e.g., 5 sessions/hour) — prevents anonymous ID multiplication for DDoS (each anonymous ID gets its own per-user rate limit bucket; without capping session creation, an attacker can spawn unlimited buckets)

**Modified:** `POST /v1/users/claim-anonymous`
- Requires both `X-Anonymous-ID` and a new header/body field with the HMAC token
- Verifies `hmac(id, secret) == token` before transferring
- Rejects with 403 if token is missing or invalid

**Frontend:**
- On first visit (no stored anonymous ID), call the new endpoint, store `{id, token}` in localStorage
- Send `X-Anonymous-ID` as before for all requests
- On signup/claim, send both the ID and the token

**Migration:** None. Existing anonymous users lose the ability to claim (not their session). The window is narrow and low-impact — anonymous sessions are ephemeral.

## Assumptions

- `anonymous_session_secret` goes in `.env.sops` (new secret, generated once)
- HMAC-SHA256 is sufficient
- No need to validate anonymous IDs on every request — only on claim. The ID itself is still opaque for document ownership.

## Done When

- Anonymous IDs are server-issued via new endpoint
- `claim-anonymous` verifies HMAC before transferring
- Frontend updated to use the new flow
- Old anonymous IDs (no token) gracefully rejected on claim

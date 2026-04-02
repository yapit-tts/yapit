# Auth

See [[stack-auth]] for the full Stack Auth integration reference (architecture, auth modes, user model, self-hosted gotchas, dev setup, key files).

This file covers auth concepts at the gateway level.

## Auth Modes

Three modes (`gateway/auth.py`):

1. **Selfhost** — When `auth_enabled=False`, all endpoints return a static `SELFHOST_USER` (no auth provider needed). Default for `make self-host`.
2. **Bearer token** — Validated against Stack Auth → returns `User`
3. **Anonymous ID** — `X-Anonymous-ID` + `X-Anonymous-Token` headers → creates anonymous user with `anon-{uuid}` ID

WebSocket uses query params (`?token=...` or `?anonymous_id=...&anonymous_token=...`).

`authenticate_optional` returns `None` instead of 401 when no credentials provided — used for unified endpoints that serve both public/shared and private documents.

## Anonymous → Registered Flow

1. User browses anonymously with `X-Anonymous-ID` header
2. Creates documents, uses browser TTS
3. Signs up via Stack Auth
4. Frontend calls `POST /v1/users/claim-anonymous` with both tokens
5. Documents transferred from `anon-{uuid}` to real user ID

## Account Deletion

`DELETE /v1/users/me` — cancels Stripe subscription, deletes documents (cascades), anonymizes billing data, deletes from Stack Auth.

## Config

See [[env-config]] for env var management. Auth-specific vars: `STACK_AUTH_API_HOST`, `STACK_AUTH_PROJECT_ID`, `STACK_AUTH_SERVER_KEY`.

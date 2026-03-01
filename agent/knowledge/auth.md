# Auth

See [[stack-auth]] for the full Stack Auth integration reference (architecture, auth modes, user model, self-hosted gotchas, dev setup, key files).

This file covers auth concepts at the gateway level.

## Auth Modes

Two ways to authenticate (`gateway/auth.py`):

1. **Bearer token** — Validated against Stack Auth → returns `User`
2. **Anonymous ID** — `X-Anonymous-ID` header → creates anonymous user with `anon-{uuid}` ID

WebSocket uses query params (`?token=...` or `?anonymous_id=...`).

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

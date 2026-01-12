# Auth

Stack Auth integration for user authentication.

## How It Works

Stack Auth runs as a separate container, provides:
- User management (signup, login, OAuth)
- Session tokens
- Dashboard at `auth.yapit.md`

Gateway validates tokens against Stack Auth API. See `gateway/auth.py` for the `authenticate()` dependency.

## Auth Modes

Two ways to authenticate (`gateway/auth.py`):

1. **Bearer token** — Validated against Stack Auth → returns `User`
2. **Anonymous ID** — `X-Anonymous-ID` header → creates anonymous user with `anon-{uuid}` ID

WebSocket uses query params (`?token=...` or `?anonymous_id=...`).

## User Model

See `gateway/stack_auth/users.py` — includes `is_anonymous`, `client_metadata` (editable by client), `client_read_only_metadata` (tier info), `server_metadata` (admin flag).

## Anonymous → Registered Flow

1. User browses anonymously with `X-Anonymous-ID` header
2. Creates documents, uses browser TTS
3. Signs up via Stack Auth
4. Frontend calls `POST /v1/users/claim-anonymous` with both tokens
5. Documents transferred from `anon-{uuid}` to real user ID

## Account Deletion

`DELETE /v1/users/me` — cancels Stripe subscription, deletes documents (cascades), anonymizes billing data, deletes from Stack Auth.

## Email Setup

Stack Auth uses Resend (SMTP) + Freestyle (template rendering) for verification/password reset emails.

**Gotchas:**
- Port 465 blocked by Hetzner firewall — use 587 with STARTTLS
- Freestyle API key required — Stack Auth can't render emails without `STACK_FREESTYLE_API_KEY`
- Startup is slow (~90 seconds) — copies many files at startup before health checks pass

See [[stack-auth-email-setup]] for full debugging history and Docker Swarm gotchas.

## Config

See [[env-config]] for env var management. Auth-specific vars: `STACK_AUTH_API_HOST`, `STACK_AUTH_PROJECT_ID`, `STACK_AUTH_SERVER_KEY`.

## Dev Setup

Dev uses `init-db.sql` dump to pre-create the yapit project. See [[dev-setup]].

Prod: Project created manually once, credentials in `.env.sops`.

## Key Files

| File | Purpose |
|------|---------|
| `gateway/auth.py` | `authenticate()` dependency |
| `gateway/stack_auth/users.py` | User model, API calls |
| `gateway/stack_auth/api.py` | Stack Auth API client |
| `gateway/api/v1/users.py` | User endpoints (claim, delete) |
| `dev/init-db.sql` | Dev database seed |

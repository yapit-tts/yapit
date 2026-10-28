# Auth

The gateway signs people in itself (`yapit/gateway/auth/`), with no auth server beside it. People sign in by email, with a link or a code and no password; the browser then holds a session cookie, and scripts use API tokens. The tables are `useraccount`, `oauthidentity`, `authsession` and `emailchallenge` (`gateway/domain_models.py`).

## Who a request is

`identify_caller` (`gateway/auth/__init__.py`) checks, in order:

1. **Selfhost**: with `AUTH_ENABLED=false`, every request is the static `SELFHOST_USER` and no auth table is read. Default for `make self-host`.
2. **Bearer API token**: `Authorization: Bearer yapit_…`, an `authsession` row of kind `api`. See [API tokens](#api-tokens).
3. **Session cookie**: `__Host-yapit_session` over https (`yapit_session` over plain http), an `authsession` row of kind `browser`. See [Sessions](#sessions). A cookie that opens no live session is ignored.
4. **Anonymous session**: `X-Anonymous-ID` + `X-Anonymous-Token` headers, giving an anonymous user with id `anon-{uuid}` ([[guest-users]]).

Session tokens, API tokens, sign-in link tokens and codes are stored only as SHA-256 hashes.

`authenticate_optional` returns `None` instead of 401 when there are no credentials, for endpoints that serve both public/shared and private documents.

**CSRF:** a cookie-authenticated request with an unsafe method (anything but GET/HEAD/OPTIONS) needs `Origin` equal to `APP_URL`'s origin, else 403. Signing in (`/v1/auth/email/verify`) and signing out check it too.

**WebSocket** (`authenticate_ws`): a bearer API token header, else the session cookie (the handshake's `Origin` must be the app's), else `?anonymous_id=…&anonymous_token=…`.

The frontend and the API share an origin everywhere, so the browser sends the cookie on its own and the frontend never handles a token. In prod and selfhost, nginx proxies `/api/` to the gateway; in dev, Vite does (`frontend/vite.config.ts`).

## Sessions

Signing in starts a browser session: a random 32-byte token in the cookie `__Host-yapit_session` (`yapit_session` over plain http, since the prefix requires Secure; HttpOnly, SameSite=Lax, Path=/, and Secure when `APP_URL` is https). The gateway keeps no state in the cookie; it looks the token's hash up in `authsession` on every request.

A session lives `SESSION_LIFETIME` and slides: a request on a session with less than `SESSION_RENEW_BELOW` left extends it to the full lifetime, and that response sets the cookie again so that the browser's copy expires with the row (`gateway/auth/sessions.py`). `GET /v1/auth/session` re-sets the cookie on every call as well.

Sign-out deletes the session's row, and account deletion deletes all of the user's rows, so either ends the session on the next request. Ending one lost device's session is a SQL delete on its `authsession` row.

## API tokens

An API token is `yapit_` followed by 32 random bytes, sent as `Authorization: Bearer`. It is an `authsession` row of kind `api` with a label and no expiry. Bearer requests skip the Origin check, since no browser attaches the header on its own. yapit-cli reads its token from `YAPIT_TOKEN`.

`scripts/create_user.py` mints one straight into the database: it creates the user, or finds the one holding the email, and prints a new token on stdout. Revoking a token is deleting its row.

## Email sign-in

1. `POST /v1/auth/email/start {email}` (202) creates an `emailchallenge` and mails one message holding a link (`{APP_URL}/auth/email#token=…&email=…`) and a 6-digit code. The token sits in the URL fragment, which browsers never send, so no access log holds it. `start` also sets the httpOnly `yapit_signin_pending` cookie, a nonce whose hash the challenge stores; a browser keeps one nonce for every link it asks for. The answer is the same whether or not an account holds the address.
2. `POST /v1/auth/email/verify {token, same_browser_only?}` or `{email, code}` signs in: it starts a browser session, sets the cookie and answers like `GET /v1/auth/session`. The first sign-in with a new address creates the account, so sign-up and sign-in are one flow. Emails are stored lowercased and trimmed.

Limits, all in `gateway/auth/email_sign_in.py`:

- A link or code works once, before its challenge expires (`CHALLENGE_LIFETIME`).
- `MAX_CODE_ATTEMPTS` wrong codes kill the address's live challenges.
- An address gets at most `MAX_CHALLENGES_PER_ADDRESS` challenges per `CHALLENGE_LIFETIME`; the next one is a 429.
- Both endpoints carry a per-IP slowapi limit (`api/v1/auth.py`).

The link's page (`/auth/email`) first posts the token with `same_browser_only`: in the browser that asked for the link, the pending cookie comes along and it signs in at once. Anywhere else (a mail scanner opening every link, another device) the gateway answers 409 and consumes nothing, and the page shows a "Continue as <email>" button that posts the token alone.

The code is for opening the mail on another device.

## Email delivery

`SMTP_*` configure stdlib `smtplib` (`gateway/auth/mailer.py`): TLS from the start on port 465, STARTTLS on any other port. With `SMTP_HOST` empty, the message goes to the gateway log instead, which is where dev reads its sign-in links. A failed send fails the request with 502 and logs an error; nothing is queued.

Prod sends through Resend on port 587; the Hetzner firewall blocks outgoing port 465.

## Endpoints

- `GET /v1/auth/session` → always 200 `{auth_enabled, user: {id, email, name, identities} | null}`. The frontend's `AuthProvider` (`frontend/src/hooks/useAuthUser.tsx`) reads it on load.
- `POST /v1/auth/email/start`, `POST /v1/auth/email/verify`: above.
- `POST /v1/auth/sign-out` → 204, deletes the session row and the cookie.

## Anonymous to registered flow

1. User browses anonymously with `X-Anonymous-ID` header
2. Creates documents, uses browser TTS
3. Signs in by email
4. Frontend calls `POST /v1/users/claim-anonymous` with both tokens
5. Documents transferred from `anon-{uuid}` to real user ID

## Account deletion

`DELETE /v1/users/me` cancels Stripe subscription, deletes documents (cascades), anonymizes billing data, deletes the `useraccount` row (its sessions, API tokens and OAuth identities cascade).

## Multi-user selfhost

`make self-host` runs single-user, with `AUTH_ENABLED=false`. For several people on one instance, set in `.env.selfhost`:

1. `AUTH_ENABLED=true`.
2. `ANONYMOUS_SESSION_SECRET` to a random string, e.g. the output of `openssl rand -hex 32`.
3. `APP_URL` to the exact origin people open Yapit at, scheme and port included (`https://yapit.example.org`, or `http://192.168.1.20` on a LAN). Sign-in links point there, and the gateway refuses cookie requests from any other origin. Over https the cookie is Secure.
4. `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD` and `SMTP_SENDER` from your mail provider. `SMTP_SENDER` is the From address, and the provider must allow sending from it. Leave `SMTP_HOST` empty to try it out first: sign-in mails then appear in `make self-host-logs`.

Then `make self-host` again. Anyone with an email address can sign up; there is no invite list.

A script or yapit-cli against a multi-user instance needs an API token. On the selfhost machine, from a checkout of this repo:

```
uv run python scripts/create_user.py --email you@example.org --label cli \
  --database-url postgresql+asyncpg://yapit:yapit@localhost:5432/yapit
```

The gateway refuses to start while any of `APP_URL` and `SMTP_*` is missing from `.env.selfhost`, since `Settings` has no defaults. An `.env.selfhost` from before these variables existed needs them copied in from `.env.selfhost.example`.

## Users migrated from Stack Auth

Before the gateway had auth of its own, a self-hosted Stack Auth container signed people in. Alembic revision `5154eb03f6c9` creates the gateway's tables and, on a database that holds Stack Auth's tables (prod, and selfhosts that ran `make self-host-auth`), copies its users across with their ids:

- `ProjectUser` → `useraccount`: id, primary email (lowercased) and display name.
- `ProjectUserOAuthAccount` → `oauthidentity`.

Since every id stays the same, the documents, subscriptions and Stripe `metadata.user_id` that name a user still name the same person. Password users sign in by email from then on, with the address their account has. The migration skips users of Stack Auth's internal (dashboard) project, users without a primary email, and, of two users sharing an email, the one active less recently. It logs the ids it skips. Stack Auth sessions do not carry over: everyone signs in once more.

The migration leaves Stack Auth's tables (PascalCase: `ProjectUser`, `ContactChannel`, …) as they were. They are the rollback path: redeploying a commit from before the cutover brings Stack Auth back on the same data, provided its compose file names the image prod's `yapit_stack-auth` service ran, by digest. `ghcr.io/yapit-tts/stack-auth:latest` is a later stopgap build that exits on start. Users who signed up after the cutover exist only in `useraccount`.

## Dev and tests

`make dev-token` prints an API token for `dev@example.com`; `make dev-cpu` creates that user. The integration tests mint a token per user with `scripts/create_user.py`. Sign-in mails in dev go to the gateway log.

## Config

`AUTH_ENABLED`, `APP_URL` (the public origin: sign-in links, the Origin check, the cookie's Secure flag), `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_SENDER`, `ANONYMOUS_SESSION_SECRET`. See [[env-config]].

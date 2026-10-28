# Auth

The gateway signs people in itself (`yapit/gateway/auth/`): passwordless email sign-in, browser sessions in a cookie, and API tokens for scripts. The tables are `useraccount`, `oauthidentity`, `authsession` and `emailchallenge` (`gateway/domain_models.py`).

## Who a request is

`identify_caller` (`gateway/auth/__init__.py`) checks, in order:

1. **Selfhost**: with `AUTH_ENABLED=false`, every request is the static `SELFHOST_USER` and no auth table is read. Default for `make self-host`.
2. **Bearer API token**: `Authorization: Bearer yapit_…`, an `authsession` row of kind `api`. No expiry; exempt from the Origin check. For the CLI, scripts and tests.
3. **Session cookie**: `__Host-yapit_session` when `APP_URL` is https, so no subdomain can plant or overwrite it, and `yapit_session` over plain http (HttpOnly, SameSite=Lax, Path=/, Secure with https), an `authsession` row of kind `browser`. Its expiry slides: a request on a session with under `SESSION_RENEW_BELOW` left extends it to `SESSION_LIFETIME` and re-sets the cookie (`gateway/auth/sessions.py`). A cookie that opens no live session is ignored.
4. **Anonymous session**: `X-Anonymous-ID` + `X-Anonymous-Token` headers → an anonymous user with id `anon-{uuid}`.

Session and API tokens, sign-in link tokens and codes are stored only as SHA-256 hashes.

`authenticate_optional` returns `None` instead of 401 when there are no credentials, for endpoints that serve both public/shared and private documents.

**CSRF:** a cookie-authenticated request with an unsafe method (anything but GET/HEAD/OPTIONS) needs `Origin` equal to `APP_URL`'s origin, else 403. Signing in (`/v1/auth/email/verify`) and signing out check it too.

**WebSocket** (`authenticate_ws`): a bearer API token header, else the session cookie (the handshake's `Origin` must be the app's), else `?anonymous_id=…&anonymous_token=…`.

The frontend and the API share an origin everywhere, so the browser sends the cookie on its own and the frontend never handles a token: in prod nginx proxies `/api/` to the gateway, in dev Vite does (`frontend/vite.config.ts`).

## Email sign-in

1. `POST /v1/auth/email/start {email}` (202) creates an `emailchallenge` and mails one message holding a link (`{APP_URL}/auth/email#token=…&email=…`) and a 6-digit code. The token sits in the URL fragment, which browsers never send, so no access log holds it. `start` also sets the httpOnly `yapit_signin_pending` cookie, a nonce whose hash the challenge stores; a browser keeps one nonce for every link it asks for. The answer is the same whether or not an account holds the address.
2. `POST /v1/auth/email/verify {token, same_browser_only?}` or `{email, code}` signs in: it starts a browser session, sets the cookie and answers like `GET /v1/auth/session`. The first sign-in with a new address creates the account; emails are stored lowercased and trimmed.

Limits: a link or code works once, before its challenge expires (`CHALLENGE_LIFETIME`); `MAX_CODE_ATTEMPTS` wrong codes kill the address's live challenges; an address gets at most `MAX_CHALLENGES_PER_ADDRESS` challenges per `CHALLENGE_LIFETIME` (429), all in `gateway/auth/email_sign_in.py`. Both endpoints carry a per-IP slowapi limit (`api/v1/auth.py`).

The link's page (`/auth/email`) first posts the token with `same_browser_only`: in the browser that asked for the link, the pending cookie comes along and it signs in at once. Anywhere else (a mail scanner opening every link, another device) the gateway answers 409 and consumes nothing, and the page shows a "Continue as <email>" button that posts the token alone.

## Email delivery

`SMTP_*` configure stdlib `smtplib` (STARTTLS, or TLS on port 465). With `SMTP_HOST` empty the message goes to the gateway log instead, which is where dev reads its sign-in links. A failed send fails the request with 502 and logs an error; nothing is queued.

## Endpoints

- `GET /v1/auth/session` → always 200 `{auth_enabled, user: {id, email, name, identities} | null}`. The frontend's `AuthProvider` (`frontend/src/hooks/useAuthUser.tsx`) reads it on load; it also refreshes the cookie.
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

## Users migrated from Stack Auth

Revision `5154eb03f6c9` copies Stack Auth's users (non-internal projects) into `useraccount`/`oauthidentity` with their ids, when the Stack Auth tables exist. Stack Auth sessions do not carry over; everyone signs in once more.

## Dev and tests

`scripts/create_user.py` creates a user directly in the database and prints a new API token; `make dev-token` prints one for `dev@example.com`. The integration tests mint a token per user that way.

## Config

`AUTH_ENABLED`, `APP_URL` (the public origin: sign-in links, the Origin check, the cookie's Secure flag), `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_SENDER`, `ANONYMOUS_SESSION_SECRET`. See [[env-config]].

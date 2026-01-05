# Stack Auth Development Setup

## The `init-db.sql` Dump

`dev/init-db.sql` is a PostgreSQL dump used **only in development** (mounted via `docker-compose.dev.yml`). It contains:

- Full Stack Auth schema (tables, types, constraints)
- Pre-configured "Stack Dashboard" internal project
- Pre-created "yapit" project with hardcoded credentials matching `.env.dev`:
  - Project ID: `a12651bb-7824-459d-b424-21a0950ab902`
  - API keys: `pck_8ny...`, `ssk_0fq...`

**Why it exists**: Avoids manual "log into dashboard → create project → copy keys" on every fresh `docker compose down -v`.

**Production uses a different approach**: The yapit project was created manually once via the Stack Auth dashboard, credentials stored in `.env.sops`.

## Stack Auth Seed Environment Variables

Stack Auth provides `STACK_SEED_*` variables, but they **only configure the internal dashboard project**, not custom app projects:

```
STACK_SEED_INTERNAL_PROJECT_SIGN_UP_ENABLED=true
STACK_SEED_INTERNAL_PROJECT_OTP_ENABLED=true
STACK_SEED_INTERNAL_PROJECT_ALLOW_LOCALHOST=true
STACK_SEED_INTERNAL_PROJECT_USER_EMAIL=admin@example.com
STACK_SEED_INTERNAL_PROJECT_USER_PASSWORD=...
STACK_SEED_INTERNAL_PROJECT_OAUTH_PROVIDERS=github,google
```

There's no built-in way to seed custom projects via environment variables. The intended workflow is: seed dashboard → admin logs in → creates projects manually → projects get random IDs/keys.

## When to Regenerate the Dump

If Stack Auth releases a breaking schema change that makes the dump incompatible, regenerate it:

1. Start fresh Stack Auth with empty DB
2. Let it seed the internal dashboard
3. Log into dashboard, create "yapit" project
4. Copy the new project ID and API keys to `.env.dev`
5. `pg_dump` the database

Or consider switching to a bootstrap script approach (more complex but always compatible).

## Sources

- [Stack Auth Self-Host Docs](https://docs.stack-auth.com/docs/js/others/self-host)
- [Stack Auth Docker .env](https://github.com/stack-auth/stack-auth/blob/dev/docker/server/.env)
- [GitHub Issue #265 - Self-host Docker](https://github.com/stack-auth/stack-auth/issues/265)

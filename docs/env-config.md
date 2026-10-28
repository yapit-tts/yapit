# Environment & Config

## Backend Files

| File | Purpose | In Git |
|------|---------|--------|
| `.env.sops` | Encrypted secrets (SOPS + age) | Yes |
| `.env` | Decrypted secrets for local dev | No |
| `.env.dev` | Public dev config | Yes |
| `.env.prod` | Non-sensitive prod config | Yes |
| `.env.template` | Documents required secrets | Yes |
| `.env.selfhost.example` | Selfhost config, copied to `.env.selfhost` | Yes |

## Frontend Files

| File | Purpose |
|------|---------|
| `frontend/.env.development` | Local dev (API base URL; Vite proxies it) |
| `frontend/.env.production` | Production build |
| `frontend/.env.selfhost` | Selfhost build |

The frontend has no auth config: it asks the gateway (`GET /v1/auth/session`) whether auth is on.

## Encrypted Secrets (.env.sops)

Naming convention:
- `DEV_*` → dev only (prefix stripped by `make dev-env`)
- `PROD_*` → prod only (prefix stripped by `make prod-env` / deploy)
- `_*` → never copied (reference/inactive)
- No prefix → shared (copied to both dev and prod)

**Edit secrets:**
```bash
SOPS_AGE_KEY_FILE=~/.config/sops/age/yapit.txt sops .env.sops
```

Age private key location: `~/.config/sops/age/yapit.txt`

## Dev vs Prod

**For dev:** `make dev-env` decrypts `.env.sops`, applies convention (removes `PROD_*` and `_*`, strips `DEV_` prefix), creates `.env`.

**For prod:** `make prod-env` applies the same convention for prod (removes `DEV_*` and `_*`, strips `PROD_` prefix); `make deploy` copies the result to the VPS. It also serves local prod operations (e.g., Stripe IaC, diagnosing prod issues).

On the VPS the gateway loads `.env`, then `.env.prod`, so a variable in `.env.prod` overrides the secret of the same name. Secrets such as `SMTP_PASSWORD` therefore live only in `.env.sops`, not as empty lines in `.env.prod`.

## Reading Config

Read `.env.dev` in full — it has all public config with comments explaining each variable.


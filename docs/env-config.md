# Environment & Config

## Backend Files

| File | Purpose | In Git |
|------|---------|--------|
| `.env.sops` | Encrypted secrets (SOPS + age) | Yes |
| `.env` | Decrypted secrets for local dev | No |
| `.env.dev` | Public dev config (ports, Stack Auth dev project) | Yes |
| `.env.prod` | Non-sensitive prod config | Yes |
| `.env.template` | Documents required secrets | Yes |

## Frontend Files

| File | Purpose |
|------|---------|
| `frontend/.env.development` | Local dev (API URLs, Stack Auth) |
| `frontend/.env.production` | Production build |

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

**For prod:** GitHub Actions deploy applies same convention for prod (removes `DEV_*` and `_*`, strips `PROD_` prefix). `make prod-env` can be used locally for prod operations (e.g., Stripe IaC, diagnosing prod issues).

## Reading Config

Read `.env.dev` in full — it has all public config with comments explaining each variable.

## Frontend Client Keys

Stack Auth CLIENT_KEY is intentionally public (embedded in JS bundle). Safe to commit in `frontend/.env.production`.

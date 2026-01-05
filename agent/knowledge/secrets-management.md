# Secrets Management (SOPS + Age)

We use SOPS with age encryption for version-controlled secrets.

## Why This Approach

Dokploy clones fresh on each deploy, wiping manually created files. SOPS lets us:
- Commit encrypted secrets to git (`.env.sops`)
- Decrypt at deploy time
- Keep Dokploy's deployment features (zero-downtime, rollbacks, etc.)

## Test vs Live Keys Pattern

For services with test/live modes (Stripe), we store both variants in `.env.sops`:
```
STRIPE_SECRET_KEY_TEST=sk_test_...
STRIPE_SECRET_KEY_LIVE=sk_live_...
STRIPE_WEBHOOK_SECRET_TEST=whsec_...
STRIPE_WEBHOOK_SECRET_LIVE=whsec_...
```

**For dev:** `make dev-env` transforms `*_TEST` → main var names, removes `*_LIVE`:
- `STRIPE_SECRET_KEY_TEST` → `STRIPE_SECRET_KEY`
- Removes `STRIPE_SECRET_KEY_LIVE`
- Also removes `STACK_*` (Stack Auth prod config)

**For prod:** Deploy script uses `*_LIVE` values directly.

## Key Locations

| Location | Purpose |
|----------|---------|
| Local: `~/.config/sops/age/yapit.txt` | Age private key (for decryption) |
| Env var: `YAPIT_SOPS_AGE_KEY_FILE` | Points to key file |
| Repo: `.env.sops` | Encrypted secrets (committed) |
| Repo: `.env.template` | Documents required secrets |

## Workflow

### Edit secrets locally
```bash
SOPS_AGE_KEY_FILE=~/.config/sops/age/yapit.txt sops .env.sops
```

### Deploy
```bash
export YAPIT_SOPS_AGE_KEY_FILE=~/.config/sops/age/yapit.txt
./scripts/deploy.sh
```

This syncs secrets to Dokploy (idempotent), then triggers deployment via API.

## File Organization

```
.env.prod     # Non-sensitive prod config (committed)
.env          # Decrypted secrets for local dev (gitignored)
.env.sops     # Encrypted secrets (committed)
.env.template # Documents required secrets
```

**Local dev:** `make dev-env` decrypts `.env.sops` → `.env`, which docker-compose reads.

**Production (Dokploy):** `deploy.sh` automatically syncs secrets before deploying. It decrypts `.env.sops` locally and sends to Dokploy via SSH API. Dokploy stores them in its database and injects at runtime — no `.env` file exists on the VPS.

## Frontend Client Keys

Stack Auth CLIENT_KEY is intentionally public (embedded in JS bundle). Safe to commit in `frontend/.env.production`.

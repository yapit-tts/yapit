# Secrets Management (SOPS + Age)

We use SOPS with age encryption for version-controlled secrets.

## Why This Approach

Dokploy clones fresh on each deploy, wiping manually created files. SOPS lets us:
- Commit encrypted secrets to git (`.env.sops`)
- Decrypt at deploy time
- Keep Dokploy's deployment features (zero-downtime, rollbacks, etc.)

## Key Locations

| Location | Purpose |
|----------|---------|
| VPS: `/root/.age/yapit.txt` | Age private key (production) |
| Local: `~/.config/sops/age/yapit.txt` | Age private key (development) |
| Env var: `YAPIT_SOPS_AGE_KEY_FILE` | Points to key file |
| Repo: `.env.sops` | Encrypted secrets (committed) |
| Repo: `.env.template` | Shows what secrets are needed |

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
.env.prod          # Non-sensitive config (committed)
.env         # Decrypted secrets (gitignored)
.env.sops    # Encrypted secrets (committed)
.env.template # Documents required secrets
```

`docker-compose.prod.yml` uses:
```yaml
env_file:
  - .env        # Dokploy-injected secrets
  - .env.prod   # Non-sensitive config
```

## Frontend Client Keys

Stack Auth CLIENT_KEY is intentionally public (embedded in JS bundle). Safe to commit in `frontend/.env.production`.

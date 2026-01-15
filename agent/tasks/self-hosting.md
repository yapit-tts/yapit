---
status: active
type: implementation
started: 2026-01-05
---

# Task: Self-Hosting Support

Parent: [[soft-launch-blockers]]

## Intent

Make it easy for people to self-host Yapit with their own models/GPUs. Minimal effort approach — don't go out of our way to remove things, just make it work.

## What Self-Hosters Need

1. **`make self-host` target** — starts services without wiping DB
2. **Documentation** — README section on self-hosting
3. **Maybe `docker-compose.selfhost.yml`** — skip Stripe container if it doesn't break

## What We Already Have

- `BILLING_ENABLED=false` env var — disables billing flow
- Local bootstrap (SQL dump for Stack Auth dev user)
- Processor config is user-editable (`tts_processors.json`)
- Stack Auth works fine for self-hosting (can have multiple users)

## What We DON'T Need

- Removing Stack Auth (self-hosters can use it)
- Different seed data
- Special code paths
- If they want slimmer, they can fork

## Implementation

### Makefile Target

```makefile
.PHONY: self-host
self-host:
	docker compose -f docker-compose.selfhost.yml up -d
```

Or simpler — just document using existing compose with right env:

```makefile
.PHONY: self-host
self-host:
	@echo "Starting Yapit in self-host mode..."
	docker compose --env-file .env.selfhost up -d
```

### .env.selfhost Template

```bash
# Copy this to .env and adjust as needed

# Disable billing (no Stripe)
BILLING_ENABLED=false

# Stack Auth (use the bundled instance)
STACK_AUTH_PROJECT_ID=...
STACK_AUTH_SECRET_SERVER_KEY=...

# Database
POSTGRES_USER=yapit
POSTGRES_PASSWORD=your-secure-password
POSTGRES_DB=yapit

# Processors - edit tts_processors.json to add your own models
```

### docker-compose.selfhost.yml (Optional)

Only if Stripe container causes issues. Could just be a profile:

```yaml
# Extends docker-compose.yml but excludes stripe-related services
```

Or use Docker Compose profiles — `--profile stripe` for prod, omit for self-host.

### Documentation

Add to README.md:

```markdown
## Self-Hosting

1. Clone the repo
2. Copy `.env.selfhost.example` to `.env` and configure
3. Edit `tts_processors.json` to add your models/voices
4. Run `make self-host`
5. Access at http://localhost:5173

### Adding Custom Models

Edit `tts_processors.json`:
- Add processor config with your model endpoint
- Add voices with your voice IDs
- Restart services

### API Keys (Optional)

If you want to use Mistral OCR or other external services:
- MISTRAL_API_KEY=...
- (add others as needed)
```

## Testing

Before marking done:
1. Fresh clone
2. Follow self-host docs
3. Verify: can create account, create document, play audio
4. Verify: billing UI hidden when BILLING_ENABLED=false

## Sources

- `Makefile` — existing targets
- `docker-compose.dev.yml` — dev setup for reference
- `.env.dev` — dev config for reference

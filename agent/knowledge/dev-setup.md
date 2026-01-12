# Dev Setup

READ THE `Makefile` — it documents all common commands/workflows.

## Quick Start

```bash
make dev-cpu      # Start backend (or make dev-mac on macOS)
cd frontend && npm run dev  # Start frontend separately
```

- Backend: `localhost:8000`
- Frontend: `localhost:5173`

## Key Points

- Use `make` commands, not raw `docker compose` — they handle env vars and build steps
- Backend code changes require container restart (`make dev-cpu`)
- `make dev-user` creates test account if login fails after startup (race condition with stack-auth health check)
- See [[env-config]] for secrets management

## Testing

- `make test-local` — basic tests (no API keys needed)
- `make test` — full suite (needs API keys)
- `make check` — type checking (backend: ty, frontend: tsc + eslint)

**Running tests manually:** Use `uv run --env-file=.env.dev pytest ...` — NOT `source .venv/bin/activate && pytest`. The Settings class requires env vars from `.env.dev`.

**Test types:**
- Unit tests (`tests/yapit/`) use testcontainers — independent, don't need backend running
- Integration tests (`tests/integration/`) connect to localhost:8000 — need `make dev-cpu` running

## CI/CD

- Full CI (tests + build + deploy): ~10 minutes. Tests ~5 min, build+deploy ~5 min.
- Skip tests: Add `[skip tests]` in commit message to go straight to build+deploy
- New Docker images: After adding to CI, set ghcr.io package visibility to public (defaults to private)

## Debugging

Use info logs or set log level to debug before restarting the backend.

## Config

- No default values in Settings class — all defaults in `.env*` files only
- Test workflow defined in `.github/workflows/`

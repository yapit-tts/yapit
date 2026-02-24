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

**Running tests:** `uv run pytest tests/...` just works — `tests/conftest.py` auto-loads `.env.dev` via python-dotenv.

**Test types:**
- Unit tests (`tests/yapit/`) — testcontainers, no backend needed
- Integration tests (`tests/integration/`) — need `make dev-cpu` running

**Test architecture:** API tests use a session-scoped app (`tests/yapit/gateway/api/conftest.py`). Testcontainers, schema, and app state are created once. Between tests: DB rows deleted, Redis flushed, SQLite caches cleared. No seed data — tests create their own. Event loop is session-scoped (`pyproject.toml`). Billing test factories live in `test_billing_webhook.py`; `sync_subscription` is monkeypatched in endpoint tests.

## CI/CD

See [[ci]].

## Debugging

**When something breaks after backend changes, check container logs FIRST:**

```bash
docker logs yapit-gateway-1 --tail 200 2>&1 | grep -i "error\|exception\|traceback"
docker logs yapit-kokoro-cpu-1 --tail 200 2>&1 | grep -i "error\|exception"
```

This takes 5 seconds and catches most runtime failures (import errors, type errors, bad assumptions about external API data).

## Frontend (npm)

- **onnxruntime CUDA issue:** Fresh `npm install` may fail with "CUDA 11 binaries not supported". Fix: `npm install --onnxruntime-node-install-cuda=skip`
- **Version drift:** Always copy `package-lock.json` when setting up worktrees to avoid dependency version mismatches

## Dependencies (uv)

**Project structure:** `pyproject.toml` has:
- `dependencies` — the full gateway stack (~25 packages: FastAPI, SQLModel, Redis, Stripe, etc.)
- `test` optional group — testing (pytest, testcontainers, websockets)
- `dev` optional group — development tools (pre-commit, tyro)

**Local dev setup:**
```bash
uv sync --all-extras  # Install base + test + dev
```

**Adding dependencies:**
```bash
uv add <package>~=<version>             # Backend deps (base)
uv add --optional test <package>~=<version>   # Test deps
uv add --optional dev <package>~=<version>    # Dev tools
```

**Common mistakes:**
- `uv add <package>>=<version>` → use `~=` for compatible releases
- `uv sync` without `--all-extras` → missing test/dev deps

**Running Python:**
- Always use `uv run ...` or activate venv first
- Never bare `python` — it doesn't exist, use `uv run python`

## Config

- No default values in Settings class — all defaults in `.env*` files only
- When adding/removing config, follow the checklist in [[infrastructure]]
- Test workflow defined in `.github/workflows/`

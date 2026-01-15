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

**Test fixture gotcha:** The test fixture relies on `uv run --env-file=.env.dev` loading most Settings. But if a field triggers initialization of components needing API keys (e.g., `ai_processor=gemini` → GeminiProcessor → needs `google_api_key`), explicitly disable it in conftest.py.

**CI debugging:** When CI breaks, first find the exact commit where it started failing (`gh run list`). Don't trust error messages at face value - they may be downstream symptoms. Diff the breaking commit to find the actual cause.

## CI/CD

- Full CI (tests + build + deploy): ~10 minutes. Tests ~5 min, build+deploy ~5 min.
- Skip tests: Add `[skip tests]` in commit message to go straight to build+deploy
- New Docker images: After adding to CI, set ghcr.io package visibility to public (defaults to private)

## Debugging

Use info logs or set log level to debug before restarting the backend.

## Dependencies (uv)

**Project structure:** `pyproject.toml` has optional dependency groups:
- `gateway` — backend API (FastAPI, SQLModel, etc.)
- `test` — testing (pytest, testcontainers)
- Base `dependencies` is minimal (just pydantic for shared contracts)

**Local dev setup:**
```bash
uv sync --all-extras  # Install ALL optional deps (gateway + test)
```

**Adding dependencies:**
```bash
uv add --optional gateway <package>~=<version>  # Backend deps
uv add --optional test <package>~=<version>     # Test deps
```

**Common mistakes:**
- `uv add <package>` without `--optional` → adds to base deps (wrong!)
- `uv add <package>>=<version>` → use `~=` for compatible releases
- `uv sync` without `--all-extras` → missing gateway/test deps

**Running Python:**
- Always use `uv run ...` or activate venv first
- Never bare `python` — it doesn't exist, use `uv run python`

## Config

- No default values in Settings class — all defaults in `.env*` files only
- When adding/removing config, follow the checklist in [[infrastructure]]
- Test workflow defined in `.github/workflows/`

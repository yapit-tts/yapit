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

**Billing tests (77 tests):** The `test_billing_*.py` and `test_usage.py` files have comprehensive deterministic coverage for webhook handlers, endpoint guards, usage waterfall, ordering/idempotency, and billing sync. Shared factories live in `test_billing_webhook.py`. Convention: `sync_subscription` is monkeypatched in endpoint tests (testing gate logic, not sync behavior). See [[stripe-integration]] Testing section for the full file list and what each covers.

**Test fixture gotcha:** The test fixture relies on `uv run --env-file=.env.dev` loading most Settings. But if a field triggers initialization of components needing API keys (e.g., `ai_processor=gemini` → GeminiProcessor → needs `google_api_key`), explicitly disable it in conftest.py.

**CI debugging:** When CI breaks, first find the exact commit where it started failing (`gh run list`). Don't trust error messages at face value - they may be downstream symptoms. Diff the breaking commit to find the actual cause.

**Test speed investigation (2026-01):** Unit tests take ~40s total, but the tests themselves only take ~12s — the rest is testcontainer startup (~30s). Investigated: pytest-xdist (overhead exceeds gains for fast tests), CI service containers (slower than testcontainers), pre-started containers via env vars (2x faster but adds complexity). Conclusion: no easy wins, testcontainer startup is the bottleneck and there's no simple fix. testcontainers-python doesn't support cross-run reuse like the Java version.

## CI/CD

- Full CI (tests + build + deploy): ~10 minutes. Tests ~5 min, build+deploy ~5 min.
- Skip tests: Add `[skip tests]` in commit message to go straight to build+deploy
- New Docker images: After adding to CI, set ghcr.io package visibility to public (defaults to private)

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

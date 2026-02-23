# CI/CD

Workflow: `.github/workflows/deploy.yml`

## Pipeline

On push to `main`:
1. **Change detection** — `dorny/paths-filter` determines which images need rebuilding
2. **Tests** (parallel) — lint, unit, integration, frontend. Skipped with `[skip tests]` in commit message or `skip_tests` workflow dispatch input
3. **Build images** — only changed components, pushed to ghcr.io. Build jobs gate on tests passing (or being skipped)
4. **Deploy** — `scripts/deploy.sh` SSHes to VPS, does `docker stack deploy`. See [[vps-setup]]

~10 min total (tests ~5 min, build+deploy ~5 min). Workers build as a matrix (kokoro-cpu, kokoro-gpu, yolo-cpu, yolo-gpu) — if one fails, all cancel.

## Integration Tests in CI

`make dev-ci` builds and starts the full stack with `--wait` (blocks until all healthchecks pass or timeout at 300s).

**Bind mount permissions:** Dev overlay bind-mounts host dirs (`gateway-data`, `images`) into the gateway. Containers run as non-root (UID 1000). Docker creates missing bind mount targets as root-owned. CI pre-creates and chowns them before `make dev-ci`. When adding new bind mounts to `docker-compose.dev.yml`, add them to the CI prep step too.

**Log collection:** The "Show logs on failure" step must use the same compose flags as startup (`-p yapit-dev --env-file .env --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml`). Without matching project name, compose finds no containers.

**Env files:** CI creates a minimal `.env` (API keys, replica counts). `.env.dev` is committed and provides the rest.

## Debugging CI Failures

Find the breaking commit first (`gh run list`). Don't trust error messages at face value — they may be downstream symptoms (e.g., "gateway unhealthy" when the real issue is a dependency like postgres crashing).

Check `gh run view <id> --log-failed` for the failing job's output. If log collection shows nothing, the project name mismatch above is likely the cause.

## Workflow Dispatch

Manual triggers via `workflow_dispatch`:
- `skip_tests` — bypass test jobs
- `force_build_all` — build all images regardless of path changes

Useful for forcing image rebuilds after a failed matrix build.

## Adding New Images

New Docker images default to private on ghcr.io. After first CI build, set package visibility to public in GitHub package settings.

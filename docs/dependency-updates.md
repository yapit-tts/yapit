# Dependency Updates

## Stack Auth Update Guide

The Docker server image (`stackauth/server:<commit-sha>`) still runs, though nothing in the app talks to it ([[stack-auth]]).

### Pre-Update Checklist

- [ ] **Backup prod DB** before deploying (migrations auto-run on startup)
- [ ] **Read the commit log** between your current SHA and target: `gh api -X GET repos/stack-auth/stack-auth/commits` or browse GitHub
- [ ] **Check the entrypoint**: https://github.com/stack-auth/stack-auth/blob/main/docker/server/entrypoint.sh — env var names and migration logic may change
- [ ] **Check the .env reference**: https://github.com/stack-auth/stack-auth/blob/main/docker/server/.env — which env vars are current
- [ ] **Clone the repo** for local analysis if needed: `git clone https://github.com/stack-auth/stack-auth ~/repos/github/stack-auth/stack-auth` (full clone, not `--depth 1` — you'll need commit history)

### How to Update

**Server (Docker image):**
1. Pick a commit SHA from `main` branch (they don't use releases/tags)
2. Update `docker/Dockerfile.stackauth`: `FROM stackauth/server:<new-sha>` (verify USER hasn't changed)
3. Run `make dev-cpu` — let migrations run on dev DB
4. Check Stack Auth container logs for migration output
5. If schema changed significantly: regenerate `dev/init-db.sql` (see [[stack-auth]])

**Deploy to prod:**
1. Push to main → CI builds new stack-auth image
2. `pg_dump` prod Stack Auth DB before deploying
3. `make prod-env && make deploy`
4. Watch `docker service logs yapit_stack-auth` for migration + seed output
5. Verify dashboard at `auth.yapit.md`, user auth flows, TTS over WebSocket

### Post-Update Verification

- [ ] CSS selector for hiding profile image: `div.flex.flex-col.sm\:flex-row.gap-2:has(span.rounded-full)` — depends on AccountSettings component internals
- [ ] Sign-up, sign-in, sign-out flows
- [ ] Anonymous → registered user claim (`POST /v1/users/claim-anonymous`)
- [ ] WebSocket auth (token + anonymous)
- [ ] Account deletion
- [ ] Dashboard accessible at `auth.yapit.md` (or `localhost:8101` in dev)
- [ ] `init-db.sql` still valid (or regenerate)

### Gotchas

- **No GitHub Releases** — Stack Auth tags Docker images by commit SHA on every push to `main`. There's no semver for the server.
- **Env var drift** — They rename/remove env vars without deprecation. `STACK_DIRECT_DATABASE_CONNECTION_STRING` silently removed (Prisma v7). `STACK_RUN_MIGRATIONS` replaced by `STACK_SKIP_MIGRATIONS` (inverted logic). Always diff the current `.env` reference against ours.
- **ClickHouse mandatory** — Since Jan 28, 2026 (`484c3a63`), the migration runner requires ClickHouse unconditionally. We run a lightweight container; see [[stack-auth]].
- **`STACK_SERVER_SECRET` must be base64url** — Used for JWT signing, NOT the same as the API server key (`ssk_*`). The old server didn't validate this at runtime; the new one does. Generate with `openssl rand -base64 32 | tr '+/' '-_' | tr -d '='`.
- **Migration backfills** — Some migrations backfill data across all rows (e.g., `lastActiveAt`). Safe for small DBs but could be slow on large ones.
- **Swarm race condition on first deploy** — ClickHouse container may not be ready when stack-auth starts. Swarm doesn't support `depends_on`. A second deploy usually works. Also: Swarm bakes env_file into service specs — changing any var in `.env` restarts ALL services using that env_file (discovered during email setup debugging — Swarm env_file baking caused spurious postgres restarts).
- **Old image + new migrations = seed crash** — If the old image runs new migrations (e.g., Swarm pulls wrong image), the seed may crash on config overrides the old code doesn't understand. The fix is in the new image (commit `dff0ddd1`). Ensure CI has built the new image before deploying.

### Key Files

See [[stack-auth]] for the full file reference. Critical ones for upgrades:

| File | Why |
|------|-----|
| `docker/Dockerfile.stackauth` | Pin new commit SHA |
| `.env.dev` / `.env.prod` / `.env.template` | Clean up dead env vars |
| `frontend/src/pages/AccountSettingsPage.tsx` | CSS selector hack to verify |
| `dev/init-db.sql` | Regenerate after major upgrades |

## Defuddle Update Guide

npm package in `docker/defuddle/`. Dockerfile uses `npm ci`, so the lockfile must match package.json.

Dependabot (`.github/dependabot.yml`) opens a PR for each defuddle release once it is 7 days old. On any PR that changes the pinned version, the `defuddle bump check` workflow runs `scripts/defuddle-bump-check.mjs` and posts its report as a PR comment:

- **Supply chain.** The lockfile pins the registry's tarball, the package declares no install scripts, its provenance says upstream's release workflow built it from the version's tag, and its `dist/` rebuilds byte for byte from that commit.
- **Extraction A/B.** Both versions extract each page in `scripts/defuddle-ab-corpus.txt` from the same HTML. The comment lists which pages changed and shows the changes; the run's artifact holds every page's HTML, both outputs and the diffs.

What the check can't decide is whether each changed page is better or worse. Read the diffs against the upstream changes the comment links, then merge. To bump by hand, change the version in `package.json`, run `npm install --package-lock-only` in `docker/defuddle`, and run the script locally (`node scripts/defuddle-bump-check.mjs <old> <new>`) or push the branch as a PR.

The A/B covers the static path only. The Playwright path calls `new Defuddle(document, { url, markdown: true }).parseAsync()` on the browser bundle (`dist/index.full.js`), so a release that changes that API needs `app.js` checked by hand.

Playwright pins the Chromium build that ships in the production image (`npx playwright install`), so its version *is* our browser-security posture — bump it whenever Chromium majors move, not just when a Playwright feature is wanted. `browsers.json` in the Playwright tag says which Chromium a release carries:

```
curl -s https://raw.githubusercontent.com/microsoft/playwright/v<tag>/packages/playwright-core/browsers.json | jq -r '.browsers[] | select(.name=="chromium") | .browserVersion'
```

`npm install --package-lock-only` only re-resolves deps whose lockfile entry falls outside the declared range — a caret dep sitting at a now-vulnerable version stays put. Raise the floor in `package.json` (or `npm update <pkg>`) and re-run `npm audit` to confirm.

Verify all four extraction paths against the running container, not just one: static, static-bot (`github.com`), Playwright (any `text/plain` URL, e.g. an RFC or a raw GitHub file — the static path rejects the content type, Chromium renders it), and `html-direct` (POST `html` instead of `url`).

## Adding New Dependencies

When adding new packages, verify license compatibility with AGPL-3.0. See [[licensing]] for verification commands and compatible licenses.

---
status: active
started: 2026-02-08
deferred: true
---

# Task: Update Stack Auth (Server + Client SDK)

## Intent

Update Stack Auth from `stackauth/server:3ef9cb3` (Dec 22, 2025) + `@stackframe/react@2.8.11` to latest. ~185 server commits and ~38 SDK patch versions behind.

**Deferred (2026-02-08):** No update until a CVE or needed feature forces it. Technical risk is low but the update gains essentially nothing for us — no user-facing features, no fix for any bug we're actually experiencing. The dashboard flickering on `auth.yapit.md` is annoying but not blocking.

**Update (2026-02-10):** The SDK upgrade is now needed to fix 5 remaining frontend CVEs (3 high `tar` via bcrypt, 1 low `elliptic`, 1 low `cookie`) — all in `@stackframe/react`'s transitive deps. Can't update the SDK without also updating the server: SDK 2.8.65 expects a response format/cookie behavior the old server doesn't provide (causes `StackAssertionError: Access token in fetchNewAccessToken is invalid` — blank page for all logged-in users). This is a **coordinated server+SDK upgrade**. See [[beta-launch-security-checklist]] for full incident writeup.

## Assumptions

- Our Stack Auth DB is small (few users) — migration backfills will be fast
- ClickHouse is NOT required for self-hosted (confirmed: not in entrypoint or self-host .env)
- No breaking REST API changes to `/api/v1/users` endpoints we use (get/delete user, metadata)
- CSS selector hack for profile image hiding survives this update (source-verified)

## Sources

**Knowledge files:**
- [[dependency-updates]] — Profile image CSS selector checklist item
- [[auth]] — Full auth integration overview
- [[stack-auth-dev-setup]] — Dev setup and init-db.sql regeneration

**External docs:**
- MUST READ: [Stack Auth entrypoint.sh](https://github.com/stack-auth/stack-auth/blob/main/docker/server/entrypoint.sh) — how migrations/seeding work now
- MUST READ: [Stack Auth Docker .env](https://github.com/stack-auth/stack-auth/blob/main/docker/server/.env) — current env var reference
- Reference: [Prisma v7 upgrade PR #1064](https://github.com/stack-auth/stack-auth/pull/1064) — removed STACK_DIRECT_DATABASE_CONNECTION_STRING
- Reference: [Secret generation fix PR #1118](https://github.com/stack-auth/stack-auth/pull/1118) — dashboard secrets no longer regenerated on restart
- Reference: [Restricted users PR #1069](https://github.com/stack-auth/stack-auth/pull/1069) — new user fields
- Reference: [Config sources PR #1083](https://github.com/stack-auth/stack-auth/pull/1083) — dashboard config overhaul

**Key code files (ours):**
- MUST READ: `docker/Dockerfile.stackauth` — pin to new commit SHA
- MUST READ: `.env.dev` — clean up dead env vars
- MUST READ: `.env.prod` — clean up dead env vars
- MUST READ: `.env.template` — clean up dead env vars
- MUST READ: `frontend/src/pages/AccountSettingsPage.tsx` — CSS selector hack to verify
- MUST READ: `dev/init-db.sql` — needs regeneration after update
- Reference: `frontend/src/auth.ts` — StackClientApp constructor
- Reference: `frontend/src/App.tsx` — StackProvider/StackTheme usage
- Reference: `yapit/gateway/stack_auth/users.py` — User model (may need new fields)
- Reference: `yapit/gateway/stack_auth/api.py` — API headers

## Done When

- [ ] Docker image updated to pinned recent commit
- [ ] `@stackframe/react` bumped to latest
- [ ] Dead env vars cleaned up in all .env files
- [ ] `init-db.sql` regenerated
- [ ] CSS selector verified or updated
- [ ] All auth flows tested (sign-up, sign-in, sign-out, anonymous claim, WS auth, account deletion)
- [ ] TypeScript passes (`npm run typecheck`)
- [ ] Deployed to prod with DB backup

## Key Changes (Server, Dec 22 → Feb 7)

**Env var changes:**
- `STACK_DIRECT_DATABASE_CONNECTION_STRING` → REMOVED (use `STACK_DATABASE_CONNECTION_STRING` only)
- `STACK_RUN_MIGRATIONS=true` → dead; replaced by `STACK_SKIP_MIGRATIONS` (default: run)

**DB migrations (~22+):**
- EmailOutbox table + email pipeline
- lastActiveAt on ProjectUser (backfill)
- BranchConfigOverride table
- restrictedByAdmin fields
- Various indices

**SDK (2.8.11 → 2.8.65):**
- Internal dep bumps (jose 6, oauth4webapi 3, etc.)
- New Stripe deps (unused by us)
- react-avatar-editor → react-easy-crop
- New user fields: isRestricted, lastActiveAt

## Risk Assessment (verified by 3 independent sub-agent investigations)

| Area | Risk | Notes |
|------|------|-------|
| DB migrations | LOW | 24 migrations, all non-destructive. 5-15 sec with 7 users. Backup is only rollback. |
| init-db.sql | LOW | Dump already 46 migrations behind current image. Prisma auto-migrates. Regenerate after update. |
| Dead env vars | LOW | `STACK_RUN_MIGRATIONS` + `STACK_DIRECT_DATABASE_CONNECTION_STRING` silently ignored |
| SDK API | LOW | Same exports, additive fields only |
| CSS selector | NONE | Source-verified: `Section` div classes + Radix Avatar `<span>` structure identical in 2.8.65 |
| Auth flow | LOW | Core unchanged |

## Discussion

**ClickHouse** initially appeared to be a new requirement (PR #1032, Jan 28), but verification showed: (1) no ClickHouse code in the repo (GitHub code search = 0 results), (2) not in self-host .env, (3) not in entrypoint.sh. It's cloud-only analytics infrastructure.

**init-db.sql** is already 46 migrations behind our current pinned image (3ef9cb3). The dump's `_prisma_migrations` table records 72 applied migrations (last: `20250401220515`). Current image has 118, latest main has 140. So every fresh `docker compose down -v && up` already runs 46 migrations. Updating adds 22 more. Prisma handles incremental migration cleanly from the `_prisma_migrations` tracking table. Regenerating the dump is recommended but not blocking.

**DB migrations (detailed):** 24 new migrations analyzed individually. No DROP TABLE or irreversible data loss. DROP operations are only on computed columns (EmailOutbox status/simpleStatus) immediately recreated with updated logic. Backfills (lastActiveAt, config split) process in batches of 10,000 — with 7 users, single batch, sub-second. Most complex migration (env_to_branch_config) creates 6 temp PL/pgSQL functions but processes ~1-2 rows. No rollback support — forward-only, `pg_dump` backup required before upgrading. Expected total migration time: 5-15 seconds, total Stack Auth downtime <1 minute.

**CSS selector**: `div.flex.flex-col.sm\:flex-row.gap-2:has(span.rounded-full)` — verified by reading actual component source on GitHub. `Section` component wrapper div class list is byte-for-byte identical between old and new. `ProfileImageEditor` switched from react-avatar-editor to react-easy-crop but initial state still renders Radix `Avatar.Root` as `<span class="... rounded-full">`. No prop exists to disable profile image section (`AccountSettings` only accepts `fullPage` and `extraItems`).

**What the update actually gains us (corrected after deeper investigation):**
- `lastActiveAt` — already in our API responses (`User.last_active_at_millis`). The migration just denormalizes it to a DB column for Stack Auth's internal perf. No change for us.
- Secret generation fix (#1118) — only affects the internal dashboard project (`auth.yapit.md`). Our yapit project is separate and unaffected. May help with dashboard flickering on restart, but the 15-sec flickering we see on every dashboard visit is likely the separate "Reduce error flickering" UI fix, not this.
- Email rendering pipeline — Freestyle updated, Vercel Sandbox added as fallback. But Vercel Sandbox likely doesn't activate for self-hosted without config (no env vars in self-host reference). Our SMTP delivery (Resend) is untouched. Marginal improvement to Freestyle error handling.
- Everything else is dashboard UI, payments features we don't use, admin tools, and internal infrastructure.

**Decision (2026-02-08):** Defer indefinitely. Update when forced by CVE or needed feature. The dashboard flickering on `auth.yapit.md` is the only annoyance, and it's not worth the update effort on its own.

**Incident (2026-02-10):** During security audit, `npm audit fix` silently bumped `@stackframe/react` 2.8.11→2.8.65. This broke auth for ALL logged-in users (blank page, `StackAssertionError` on token refresh). Root cause: the new SDK makes a token refresh call to `auth.yapit.md` that the old server handles differently — the SDK rejects the response as invalid. Reverted SDK to 2.8.11. Confirmed: SDK and server must be upgraded together. Also found [known issue #1060](https://github.com/stack-auth/stack-auth/issues/1060) with v2.8.56+ and token handling changes.

**CRITICAL learning:** Never run `npm audit fix` without checking if `@stackframe/react` version changed. The SDK is semver-compatible (^2.8.11 allows 2.8.65) but functionally breaks without matching server version. Pin explicitly in package.json if this keeps happening.

**Updated decision (2026-02-10):** Still deferred but now has a concrete trigger — the remaining 5 frontend CVEs (3 high, 2 low) are all in Stack Auth's dependency tree and can only be fixed by the coordinated upgrade. These CVEs are in `tar`, `bcrypt`, `elliptic`, `cookie` — all Node.js server-side packages that are NOT in the browser bundle (Vite tree-shakes them out). So while GitHub reports them as "high", the practical risk is near-zero for our use case. No urgency.

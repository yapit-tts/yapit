# Dependency Housekeeping

**Status:** done
**Completed:** 2026-01-18

---

## Summary

Batch update of non-Stripe dependencies + SQLModel type fixes.

**Commit:** `db84107` — chore: dependency housekeeping + SQLModel type fixes

### Changes

- **psycopg2 → psycopg3**: Modern async driver for Alembic migrations
- **Removed unused**: google-re2, svix
- **Updated**: fastapi 0.128, sqlmodel 0.0.31, redis 7.1, alembic 1.18, asyncpg 0.31, pydantic 2.12, orjson 3.11, markdown-it-py 4.0, aiosqlite 0.22, and others
- **Type fixes**: Added `col()` wrapper, `lazy="selectin"` on UserSubscription.plan, removed redundant selectinload calls

### Verification

- ✅ `uv sync` — deps install cleanly
- ✅ Tests pass
- ✅ Alembic works with psycopg driver (tested migration creation)
- Type errors reduced from 92 → 48

---

## Related

- [[2026-01-14-pricing-restructure]] — Stripe SDK upgrade bundled there

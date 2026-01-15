# psycopg2 → psycopg3 Migration

**Status:** pending
**Priority:** low
**Effort:** ~5 minutes

## Context

psycopg2 is legacy (maintenance-only). psycopg3 is the modern rewrite with native async, better typing, and free-threading support for Python 3.14+.

We only use psycopg2 for Alembic migrations (runtime uses asyncpg). This is a housekeeping change — no performance benefit, but future-proofs the stack.

## Changes Required

### 1. pyproject.toml

```diff
- "psycopg2-binary~=2.9.10",
+ "psycopg[binary]~=3.2",
```

### 2. yapit/gateway/migrations/env.py:36

```diff
- return url.replace("postgresql+asyncpg://", "postgresql://")
+ return url.replace("postgresql+asyncpg://", "postgresql+psycopg://")
```

## What Stays the Same

- All existing migration files (just SQL)
- All SQLModel/SQLAlchemy ORM code
- `db.py` (uses asyncpg, untouched)
- Prod databases (driver is client-side only)
- Deploy scripts, docker-compose

## Verification

1. `uv sync` — deps install cleanly
2. `make dev-cpu` — gateway starts
3. `alembic upgrade head` — migrations still run
4. (Optional) `alembic revision --autogenerate -m "test"` — generates empty migration

## Related

- [[overview]] — for general architecture context
- Session: `python-3.14-free-threading-feasibility-analysis-psycopg3-migration`

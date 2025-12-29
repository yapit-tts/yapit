---
status: done
type: implementation
---

**Knowledge extracted:** None - tooling setup documented in CLAUDE.md and pyproject.toml. Fixes are in codebase.

# Task: Set up type checking with ty

## Goal

Add `make check` command that runs type checking on the backend. Configure ty to:
- Exclude files that can't be type-checked in dev (workers with GPU deps)
- Fix real type issues where sensible
- Ignore false positives (SQLAlchemy ORM patterns, etc.)

## Result

✅ **Complete.** `make check` now runs type checking for both backend and frontend.

### What was done:

**Backend (ty):**
- Added `[tool.ty]` config in pyproject.toml
- Excluded `yapit/workers/` (GPU deps not installed in dev)
- Expanded redis stubs (`yapit/stubs/redis/asyncio/client.pyi`) to cover all methods used
- Fixed transformer.py type issues with proper casts
- Fixed SQLAlchemy column methods (`.desc()`, `.in_()`) using `col()` wrapper
- Added inline ignores for SDK limitations (Mistral **kwargs, get_settings ellipsis)

**Frontend:**
- Fixed `{}` type error in api.tsx → `PropsWithChildren`
- Already had strict TypeScript + ESLint (9 warnings, 0 errors)

### Files changed:
- `pyproject.toml` - ty config
- `Makefile` - check/check-backend/check-frontend commands
- `CLAUDE.md` - added `make check` hint
- `yapit/stubs/redis/asyncio/client.pyi` - expanded redis stubs
- `yapit/gateway/processors/markdown/transformer.py` - type casts
- `yapit/gateway/api/v1/documents.py` - col() wrapper
- `yapit/gateway/api/v1/ws.py` - col() wrapper
- `yapit/gateway/config.py` - inline ignore
- `yapit/gateway/processors/document/mistral.py` - inline ignore
- `frontend/src/api.tsx` - PropsWithChildren fix

---

## Work Log

### 2025-12-29 - Implementation complete

**Analysis phase:**
- Ran `ty check yapit/` - found 36 diagnostics
- Categorized: 11 unresolved-import (workers), 9 invalid-argument-type, 3 invalid-await (redis), 3 call-non-callable, 2 unresolved-attribute (SQLAlchemy), 1 invalid-return-type

**Key findings:**
- Workers directory imports torch/transformers/kokoro - excluded since GPU deps only in Docker
- SQLAlchemy Column methods (`.desc()`, `.in_()`) need `col()` wrapper from sqlmodel
- redis-py async types incomplete - expanded custom stubs
- Mistral SDK doesn't handle **kwargs typing well - SDK limitation, inline ignore
- get_settings() uses ellipsis body intentionally (FastAPI DI pattern) - inline ignore

**Fixes applied:**
1. Frontend `{}` type → `PropsWithChildren` (trivial)
2. transformer.py: Added casts for markdown-it attr types (`Literal[1,2,3,4,5,6]`, `int | None`, `str`)
3. SQLAlchemy: Changed `Document.created.desc()` → `col(Document.created).desc()`
4. Redis stubs: Added pubsub, brpop, llen, lpush, set, exists, delete, publish methods
5. Added ty config: exclude workers, extra-paths for stubs

**Tests status:**
- Tests have some type issues but not configured for checking yet (different typing needs)
- Main gateway code passes clean

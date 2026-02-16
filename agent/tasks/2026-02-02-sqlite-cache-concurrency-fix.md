---
status: done
started: 2026-02-02
completed: 2026-02-02
---

# Task: Fix SQLite Cache Concurrency (database locked errors)

## Intent

`SqliteCache` produces "database is locked" 500 errors on prod under even light concurrent load (~3 users). Root cause: connection-per-operation pattern with no `busy_timeout`, combined with `retrieve_data` writing on every read (LRU `last_accessed` update).

Must scale to hundreds of concurrent users with 50-100GB cache databases.

## Assumptions

- SQLite stays as the cache backend (R2 ruled out — more complexity, disk space solvable via bigger VPS or Hetzner volumes)
- LRU semantics are required for eviction (FIFO not acceptable)
- All three caches (audio, document, extraction) share the same `SqliteCache` class

## The Fix

1. **Persistent connection** — single `aiosqlite` connection held as instance state, not connect-per-operation
2. **`PRAGMA busy_timeout=5000`** — safety net for any remaining lock contention
3. **Batched LRU updates** — accumulate accessed keys in memory, flush periodically instead of writing on every read. Makes `retrieve_data` a pure read in WAL mode (unlimited concurrent readers).
4. **Batch eviction** — single `DELETE ... WHERE key IN (SELECT ... ORDER BY last_accessed LIMIT ?)` instead of loop

## Done When

- No "database is locked" errors under concurrent load
- `retrieve_data` is a pure read (no write lock taken)
- LRU eviction still works correctly
- Existing tests pass + new concurrency test

## Sources

PLAN FILE: /home/max/.claude/plans/mossy-inventing-wreath.md

**Knowledge files:**
- [[tts-flow]] — audio cache is in the hot playback path

**Key code files:**
- MUST READ: `yapit/gateway/cache.py` — the broken implementation
- MUST READ: `yapit/gateway/api/v1/audio.py` — audio serving endpoint (main read path)
- MUST READ: `yapit/gateway/result_consumer.py` — main write path (stores audio after synthesis)
- MUST READ: `yapit/gateway/synthesis.py` — cache hit checks + exists polling
- Reference: `yapit/gateway/__init__.py` — lifespan creates caches, daily vacuum task
- Reference: `yapit/gateway/deps.py` — cache dependency injection
- Reference: `tests/yapit/gateway/test_cache.py` — existing tests

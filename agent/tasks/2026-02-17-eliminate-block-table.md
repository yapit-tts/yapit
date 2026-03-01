---
status: done
started: 2026-02-17
---

# Task: Eliminate Block Table

## Intent

The Block table duplicates data already derivable from `structured_content`. Eliminating it cuts DB storage by ~47% (the single largest consumer) and simplifies the write/import paths. Not urgent — the volume migration buys plenty of headroom — but a clean architectural improvement.

## Done When

- Block table dropped via Alembic migration
- All consumers derive block data from `structured_content` instead
- `audio_characters` precomputed on Document for stats endpoint
- Verification script confirms zero mismatches on prod before migration

## Research

- [[2026-02-16-structured-content-compute-vs-store]] §3 (Block Table analysis) and §5 (migration path).
- [[2026-02-26-block-table-removal-impact]] — Full impact analysis: every file that must change, simplifications unlocked, risk assessment.

## Plan

`~/.claude/plans/temporal-plotting-peacock.md` — Implementation plan with codex review.

## Migration Path

**The migration is straightforward** because `get_audio_blocks()` is a pure extraction — it reads `AudioChunk.text` and `AudioChunk.audio_block_idx` directly from the frozen JSON. No transformation logic that could drift.

Pre-AudioChunk documents (before c9b68a6, Jan 25 2026) have an incompatible schema — no backend handling. Manually delete and re-upload any that still exist in prod before migrating. The refactor only targets post-AudioChunk documents.

### Phases

**Phase 1 — Add `audio_characters` column to Document:**
- Integer column, set at creation from `sum(len(t) for t in get_audio_blocks())`
- Backfill for existing docs from `SUM(LENGTH(Block.text))` per document
- Migrate stats endpoint to use `SUM(Document.audio_characters)`

**Phase 2 — Code migration (~6 locations):**
- WebSocket handler: parse structured_content, call `get_audio_blocks()[idx]` (~2-5ms, negligible vs 500ms+ synthesis)
- `GET /blocks` endpoint: derive from structured_content instead of DB query
- `GET /public` (block_count): `len(get_audio_blocks())` or count audio chunks in JSON
- `POST /import`: stop cloning Block rows (structured_content already cloned)
- Warm cache: derive from structured_content (already has Document loaded)
- Block creation in `create_document_with_blocks`: remove, simplify to `create_document`

**Phase 3 — Drop table:**
- Remove Block model, relationship, cascade config
- Alembic: `op.drop_table("block")`

### Pre-migration verification

Run on prod before Phase 3: for every document, compare `get_audio_blocks()` output against stored Block rows. Must be zero mismatches. Script pseudocode in research artifact.

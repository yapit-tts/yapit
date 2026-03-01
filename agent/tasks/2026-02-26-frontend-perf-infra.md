---
status: active
refs:
  - agent/tasks/frontend-performance-tracking.md
---

# Frontend Performance Benchmarking Infrastructure

## Intent

Build tooling so agents can measure frontend performance in a closed loop — seed test documents, trigger interactions, read measurements — without human involvement. This enables data-driven optimization: baseline → change → measure → compare.

The existing performance tracking task identifies several bottlenecks (j/k navigation on 10k+ blocks, tab switching on 33k blocks, O(n*m) filterVisibleBlocks) but notes "profile actual bottleneck before committing to any approach." This task delivers that profiling capability.

## Components

### 1. Test Document Fixtures (`scripts/seed_perf_fixtures.py`)

Generate documents via the `/v1/documents/text` API at escalating scales. The API handles markdown parsing, block splitting, and structured content generation — fixtures are realistic documents, not synthetic JSON.

Variants:
- **Flat** (no headings): pure block count stress test
- **Sectioned** (H1 every ~20 blocks): tests section-aware code paths (filterVisibleBlocks, useFilteredPlayback, outliner)
- **Dense sections** (H2 every ~5 blocks): worst case for O(n*m) section scanning

Sizes: 100, 500, 1k, 2k, 5k, 10k blocks. Doubling progression to see where perf degrades.

Fixtures are idempotent (skip if title already exists), so the script can be re-run safely.

### 2. Performance Monitor (`frontend/src/lib/perfMonitor.ts`)

Lightweight instrumentation wrapping hot paths with `performance.mark()`/`performance.measure()`. Exposes `window.__yapit_perf` for agent access via `evaluate_script`.

Functions to instrument:
- `deriveBlockStates()` in playbackEngine.ts — runs on every snapshot, O(n) with 3 map lookups per block
- `getSnapshot()` — to measure total snapshot cost including deriveBlockStates
- `filterVisibleBlocks()` — O(n*m) section scanning
- `useFilteredPlayback` useMemo body — downstream of snapshot changes

API:
```js
window.__yapit_perf.reset()           // clear all measurements
window.__yapit_perf.summary()         // { fnName: { calls, avg_ms, p95_ms, max_ms } }
window.__yapit_perf.measurements(name) // raw entries for one function
```

Dev-only: guarded by `import.meta.env.DEV` or stripped by tree-shaking in prod.

### 3. Agent Workflow

Full loop an agent runs via Chrome DevTools MCP:

1. Run `seed_perf_fixtures.py` (once, creates test docs)
2. `navigate_page` to `localhost:5173`, login as dev user
3. Navigate to a fixture document (by known title pattern)
4. `evaluate_script` → `window.__yapit_perf.reset()`
5. `press_key("j")` × N times (or `click` for section toggles)
6. `evaluate_script` → `window.__yapit_perf.summary()`
7. Record baseline numbers
8. Apply code change, reload
9. Repeat steps 4-6, compare

## Assumptions

- Backend is running (`make dev-cpu`) — needed for API calls and document serving.
- The `/v1/documents/text` endpoint handles block splitting. We don't need to generate structured_content JSON manually — the markdown content determines block count and section structure.
- Fixture document sizes are deterministic given the same markdown input (block splitting is deterministic).
- `performance.mark()`/`performance.measure()` overhead is negligible compared to the operations being measured.
- Chrome DevTools MCP `press_key` triggers the same code path as physical keyboard input (it does — dispatches KeyboardEvent).

## Done When

- `scripts/seed_perf_fixtures.py` creates test documents at 6 size points × 3 variants
- `window.__yapit_perf` is available in dev mode and returns measurement data
- An agent can run the full measure loop (seed → navigate → interact → read metrics) without human intervention
- Hot paths identified in the performance tracking task are instrumented

## Considered & Rejected

**Raw trace file parsing:** `performance_start_trace` saves `.json.gz` traces. Could parse these for detailed flame chart data. Rejected because: high complexity, the trace format is internal to Chrome, and our hot paths are specific JS functions better measured with `performance.measure()`. Traces are still useful for broad CWV analysis but not for targeted function-level benchmarking.

**Frontend-only test route (`/perf-test?blocks=10000`):** Render synthetic documents without DB. Rejected because: doesn't test realistic data flow (API fetch, JSON parse, block hydration), and fixtures via the API are simple enough.

**Dedicated benchmark harness (separate from app):** A standalone page that imports components and measures them in isolation. Rejected because: misses the integration context (React reconciliation, hook interactions, real component tree depth) which is where the actual perf issues manifest.

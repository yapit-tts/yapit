---
status: done
started: 2026-02-05
completed: 2026-02-07
---

# Task: Async Migration — Thread Pool Bottleneck Audit

## Intent

All external API calls in the gateway use `asyncio.to_thread()` wrapping synchronous SDK clients. They share Python's default `ThreadPoolExecutor` (~20 threads on our VPS). Under high concurrency, these calls contend for the same pool. The worst offender (RunPod overflow `run_sync`) is being fixed separately in [[2026-02-05-overflow-scanner-rewrite-dlq-fix]]. This task covers everything else — primarily Gemini, but also a thorough audit of all `to_thread`/`run_in_executor` usage.

## Assumptions

- The `google-genai` SDK (v1.61+) has native async via `client.aio.models.generate_content()` — drop-in replacement for the sync version wrapped in `to_thread`.
- Gemini calls are the second-biggest thread consumer after RunPod overflow (10-20s per call, concurrent during document extraction).
- Other `to_thread` calls (PDF parsing, trafilatura, MarkItDown) are short-lived but should still be audited.

## Sources

**External docs:**
- MUST READ: [Google GenAI SDK docs](https://googleapis.github.io/python-genai/) — `client.aio` async namespace
- Reference: [Async Vertex AI sample](https://cloud.google.com/vertex-ai/generative-ai/docs/samples/googlegenaisdk-textgen-async-with-txt)

**Knowledge files:**
- [[infrastructure]] — worker services, Docker compose structure
- [[tts-flow]] — overall architecture context

**Key code files:**
- MUST READ: `yapit/gateway/document/gemini.py` — main Gemini usage, `to_thread(self._client.models.generate_content, ...)` at line 348
- MUST READ: `yapit/gateway/document/batch.py` — Gemini batch API: `files.upload`, `batches.create`, `batches.get`, `files.download` — all via `to_thread`
- Reference: `yapit/gateway/document/website.py` — trafilatura `extract_markdown` and MarkItDown via `to_thread`
- Reference: `yapit/gateway/document/markitdown.py` — MarkItDown conversion via `to_thread`
- Reference: `yapit/gateway/api/v1/documents.py` — `_extract_document_info` (PDF page count) via `to_thread`
- Reference: `yapit/gateway/db.py` — Alembic migration via `to_thread` (startup only, not a concern)

## Done When

- [ ] Full audit: every `to_thread` / `run_in_executor` call catalogued with expected duration and concurrency risk
- [ ] Gemini `generate_content` migrated to `client.aio.models.generate_content` — no `to_thread`
- [ ] Gemini batch operations (`files.upload`, `batches.create`, `batches.get`, `files.download`) migrated to async equivalents if available in the SDK
- [ ] Any other calls identified as problematic are either migrated to async or given a dedicated executor
- [ ] Short-lived CPU-bound calls (PDF parsing, trafilatura) documented as acceptable or migrated as needed
- [ ] `make test-local` passes

## Design (preliminary)

### Gemini generate_content

Straightforward migration:
```python
# Before:
await asyncio.to_thread(self._client.models.generate_content, model=..., contents=...)

# After:
await self._client.aio.models.generate_content(model=..., contents=...)
```

Need to verify: does `client.aio` have the same retry/error surface? The current code catches `genai_errors.APIError` — confirm this works the same with async calls.

### Gemini batch operations

Check if `client.aio.batches.create`, `client.aio.files.upload`, etc. exist. If so, migrate. If not, these are less critical (lower concurrency than `generate_content` — batch operations are one per document, not one per page).

### CPU-bound calls (trafilatura, MarkItDown, PDF page extraction)

These are genuinely CPU-bound (not I/O-bound), so `to_thread` is actually correct for them — it prevents blocking the event loop during CPU work. The concern is only if they're slow enough to hold threads for extended periods under high concurrency:

- **trafilatura** `extract_markdown`: typically fast (< 1s)
- **MarkItDown** large PDF conversion: could take tens of seconds for 100+ page PDFs
- **PDF page count**: typically fast

MarkItDown on huge PDFs is the only potential concern here. Assess whether it needs a dedicated executor or if the default pool handles it fine at expected concurrency.

## Discussion

Current `to_thread` inventory (from audit):

| Location | Call | Duration | Concurrency risk |
|----------|------|----------|-----------------|
| `gemini.py:348` | `generate_content` | 10-20s | HIGH — one per page during extraction, many concurrent users |
| `batch.py:159` | `files.upload` | variable | Medium — one per batch job |
| `batch.py:170` | `batches.create` | quick API call | Low |
| `batch.py:224` | `batches.get` | quick API call | Low — polling |
| `batch.py:261` | `files.download` | variable | Medium — one per completed batch |
| `website.py:56,62` | `extract_markdown` | < 1s | Low |
| `website.py:69` | MarkItDown | variable | Low-Medium |
| `markitdown.py:44` | MarkItDown | variable, potentially tens of seconds for huge PDFs | Medium |
| `documents.py:330,400` | `_extract_document_info` | < 1s | Low |
| `db.py:60` | Alembic upgrade | startup only | None |

Primary targets: `gemini.py:348` (high impact) and `batch.py` operations (medium impact). The rest are acceptable.

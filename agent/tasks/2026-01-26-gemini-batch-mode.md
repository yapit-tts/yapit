---
status: done
started: 2026-01-26
completed: 2026-02-03
parent: [[2026-01-12-gemini-processor-integration]]
---

# Task: Gemini Batch Mode

## Intent

Add opt-in batch mode for Gemini document extraction. Users processing many documents or large books can save 50% on token costs by accepting longer processing times (target 24h, usually faster).

**Goals:**
- 50% cost savings via Gemini Batch API
- Seamless UX: user opts in, submits, can close tab, returns later
- Smart default: suggest batch mode for >100 page documents

**Non-goals:**
- Completion notifications (email/push) — defer to post-launch if needed
- Partial progress indication — batch is all-or-nothing
- Cancellation — too complex for v1 (Google bills for completed requests but results aren't retrievable on cancel, making billing reconciliation unreliable)

## Sources

**External docs:**
- MUST READ: [Gemini Batch API](https://ai.google.dev/gemini-api/docs/batch-api) — job lifecycle, file-based input, result retrieval
- Reference: [GenerateContentResponse](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/reference/rest/v1/GenerateContentResponse) — confirms `usage_metadata` in batch results

**Key code files:**
- MUST READ: `yapit/gateway/document/batch.py` — batch submission, job tracking, result retrieval
- MUST READ: `yapit/gateway/document/batch_poller.py` — background polling + document creation
- MUST READ: `yapit/gateway/document/gemini.py` — `prepare_for_batch` + `PreparedPage`
- MUST READ: `frontend/src/components/metadataBanner.tsx` — where batch toggle goes
- MUST READ: `frontend/src/components/unifiedInput.tsx` — document create flow
- Reference: `yapit/gateway/document/processing.py` — ProcessorConfig, reservation integration
- Reference: `yapit/gateway/reservations.py` — per-user Hash reservation system
- Reference: `yapit/gateway/api/v1/documents.py` — `_submit_batch_extraction`, batch status endpoint

## Key Decisions

### Architecture

- **One batch job per document** containing N requests (one per page)
- **File-based input** (JSONL upload) — handles any document size
- **File-based output** — results come back via `batch_job.dest.file_name`, NOT `inlined_responses`
- **Redis for job tracking** — `BatchJobInfo` (Pydantic) at `batch:{content_hash}`, TTL 48h
- **Active jobs Set** — `active_batch_jobs` Set tracks content_hashes needing polling (avoids SCAN)
- **Per-user reservation Hash** — `reservations:{user_id}` with content_hash fields (avoids SCAN)
- **15s fixed poll interval** — simpler than backoff, adequate for minutes-to-hours jobs

### Billing Model

| Scenario | Billing |
|----------|---------|
| Upfront check | Estimate (verify user has quota via reservation) |
| Completed successfully | Actual tokens from `usage_metadata` per page |
| Failed due to error | No charge (reservation released) |

### UX

- Batch toggle button in MetadataBanner (only when AI Transform ON)
- Hover tooltip: "Save 50% on your quota. Results usually ready in minutes, but can take up to 24 hours."
- Auto-enable for >100 pages (user can disable)
- Progress: "Batch submitted at 14:32 ☕" with cozy loading state

### API

- `POST /v1/documents/document` accepts `batch_mode: bool` (requires `ai_transform=true`, validated)
- Returns `BatchSubmittedResponse` with HTTP 202 Accepted
- `GET /v1/documents/batch/{content_hash}/status` — returns `BatchStatusResponse` with status, document_id on completion

### API Constraints

- Results only retrievable from `JOB_STATE_SUCCEEDED` jobs
- Known issues: occasional jobs stuck in PENDING >24h ([GitHub #1482](https://github.com/googleapis/python-genai/issues/1482))
- `JOB_STATE_EXPIRED` after 48h — treated same as FAILED

## Gotchas

- YOLO must complete for ALL pages before batch submission (figures needed in prompt)
- File-based batch results require `client.files.download()` — `inlined_responses` is always None for file-based jobs
- Reservation must be released on failure (try/except in `_submit_batch_extraction`)
- `BatchJobInfo.figure_urls_by_page` uses `dict[int, list[str]]` — Pydantic handles int↔str key conversion for JSON automatically

## Considered & Rejected

- **Cancellation support** — Google bills for completed requests on cancelled jobs but results can't be retrieved. Billing reconciliation (how many tokens were consumed?) is uncertain. Race conditions with concurrent cancel + completion. Deferred to post-launch.
- **Inline batch submission** — 20MB limit, not viable for large docs. File-based from the start.
- **SCAN-based Redis lookups** — O(total keys) for reservations and job listing. Replaced with Hash (reservations) and Set (active jobs).
- **Polling backoff (5s → 15s → 30s)** — Added complexity for minimal benefit. Fixed 15s interval is simple and adequate.

## Open Questions

- Retry logic for stuck PENDING jobs? (maybe auto-cancel after 24h and notify user)

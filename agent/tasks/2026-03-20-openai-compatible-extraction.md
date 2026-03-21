---
status: done
refs: ["PR #73"]
---

# OpenAI-Compatible Extraction Backend

## Intent

Two goals, one refactor:

1. **Pluggable extraction backend.** Swap Gemini for any model behind an OpenAI-compatible API — self-hosted VLM via vLLM, hosted provider, LiteLLM proxy, whatever.

2. **Proper extraction abstractions.** Right now the DI types, batch wiring, and `FormatInfo` are hardcoded to `GeminiExtractor`. Abstracting these into protocols makes the entire extraction flow testable without hitting the Gemini API — especially batch mode, which is currently impossible to test in isolation.

Implementation happens on a branch, PR stays open until we have a concrete model to validate against (community request, self-hosted VLM we want to run, etc.). The refactor itself is worth doing now so it's ready. Bonus: makes the existing batch flow testable without hitting Gemini.

## Research

- [[2026-03-20-openai-api-compatible-extraction]] — full architecture trace, Gemini SDK surface, PDF input problem, design with per-file change list

## Assumptions

- The extraction prompt (`prompts/extraction.txt`) is portable enough to work with strong VLMs (Qwen2-VL-72B, etc.) without major rewrites. If not, we'd need per-model prompt variants — but start with the same prompt and iterate.
- Most self-hosted VLMs (vLLM, Ollama) don't accept native PDF — only images. The extractor needs a `supports_pdf` flag to decide whether to render pages to PNG first. Gemini and some hosted providers (Anthropic, future OpenAI) accept PDF natively.
- `billing_enabled=false` in `.env.selfhost` already disables the billing flow. Self-hosters running their own GPU don't need per-token billing.

## Batch Mode

Batch is about cost (50% cheaper for async processing), not document size. Any document can be submitted batch. The >100 page auto-toggle in `MetadataBanner` is just a UX default.

Batch should be a protocol capability, not a Gemini-specific bolt-on. The contract is simple:

- **Submit:** pages in → job handle out
- **Poll:** handle → status
- **Collect:** handle → results

The Gemini-specific plumbing (JSONL format, file upload API, `batches.create/get`, result parsing) is the *implementation* of this contract. With a proper protocol:

- `GeminiExtractor` implements batch via its current Gemini Batch API code
- `OpenAIExtractor` could implement batch via OpenAI's Batch API (different format, same contract) — later, when needed
- `FormatInfo.batch` becomes dynamic based on whether the active extractor supports batch
- The batch orchestration (`_submit_batch_extraction`, `BatchPoller` loop, `create_document_from_batch`) becomes testable against a mock batch backend

This doesn't mean we refactor batch into a protocol *now* — but the extractor protocol should be designed with batch as an optional capability from the start, not bolted on after.

## Done When

- Extractor protocol defined with `extract()` + optional batch capability
- `AI_PROCESSOR=openai` with `AI_PROCESSOR_BASE_URL` + `_API_KEY` + `_MODEL` starts the gateway with an `OpenAIExtractor`
- PDF extraction works end-to-end: prepare → create → poll → document appears
- Image extraction works (single image input)
- PDF→PNG rendering works for `supports_pdf=false` backends
- Native PDF passthrough works for `supports_pdf=true` backends
- Batch toggle hidden in frontend when extractor doesn't support batch
- Gemini path unchanged — no regressions
- `.env.selfhost.example` documents the new config
- Extraction quality tested on a handful of representative documents with at least one open-source VLM

## Considered & Rejected

**LiteLLM as the abstraction layer** — Put LiteLLM between yapit and any provider, use OpenAI SDK everywhere. Rejected: adds a container dependency for all deployments, doesn't solve the PDF-vs-image gap (LiteLLM can't make image-only models accept PDF), and we lose direct control over retry logic / error handling. Better to own the thin adapter.

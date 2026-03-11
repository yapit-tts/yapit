---
status: done
refs:
  - "[[2026-03-05-defuddle-evaluation]]"
  - "[[2026-03-06-defuddle-arxiv-quality]]"
---

# Unified content extraction via Playwright+defuddle

## Intent

Replace trafilatura (websites) and markxiv (arXiv) with a single extraction approach: Playwright navigates to the URL, injects defuddle as a bundle into the browser DOM, extracts markdown. No separate services.

Eliminates two containers, their Dockerfiles, CI jobs, and all the complexity around JSDOM event loop blocking, sidecar concurrency, and LaTeX→pandoc pipelines.

**arXiv free path:** tries `arxiv.org/html/{id}` via Playwright+defuddle, falls back to pymupdf if no HTML version exists (~26% of papers). Paid path (Gemini via PDF) unchanged.

Branch: `defuddle-sidecar`.

## Assumptions

- Playwright Chromium is already in the gateway image — no new dependency.
- `networkidle` wait strategy is acceptable. Slow pages (4-5s) are mostly analytics scripts loading, not extraction time.
- defuddle upstream continues improving — kepano fixed 4 issues in <24h.
- Gateway memory stays manageable with every website extraction using a Chromium tab (semaphore caps at 50).
- Prod compose network allows gateway → smokescreen for Playwright proxy.

## Done when

- [ ] Docs/knowledge updated to reflect new architecture
- [ ] Branch merged to main and deployed
- [ ] Old markxiv container + volume cleaned up on prod

ArXiv output quality tracked separately in [[2026-03-06-defuddle-arxiv-quality]].

## Considered & rejected

- **JSDOM sidecar** — implemented first, abandoned. Single-threaded Node.js couldn't handle math-heavy pages (event loop blocking). Added infra complexity for a worse result than injecting defuddle into Playwright's real browser DOM.
- **Subprocess call to defuddle CLI** — Node.js cold start per call (~200-400ms).
- **Keeping markxiv for arXiv, defuddle only for websites** — unnecessary complexity. Playwright+defuddle handles arXiv HTML well, pymupdf handles the rest.
- **Conditional page selector UI for arXiv free path** — not worth the frontend complexity. Page selector shows but defuddle extracts the full paper regardless. If pymupdf fallback triggers, pages work correctly.

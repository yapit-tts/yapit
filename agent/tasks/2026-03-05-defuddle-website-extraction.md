---
status: active
refs:
  - "[[2026-03-05-defuddle-evaluation]]"
---

# Unified content extraction via defuddle

## Intent

Replace both trafilatura (websites) and markxiv (arXiv) with defuddle as the single content extraction engine, via the existing HTTP sidecar.

**Websites**: defuddle already produces better output than trafilatura — preserves list structure, standardizes footnotes/sidenotes, resolves image URLs, preserves video elements.

**arXiv**: defuddle has partial LaTeXML support and is actively improving. The free path for arXiv papers becomes:
- HTML available (~74% of papers) → defuddle (same website flow)
- No HTML → PyMuPDF (existing free PDF path)
- Paid path → VLLM via PDF (unchanged)

This eliminates markxiv entirely — no more LaTeX source → pandoc pipeline to maintain.

Branch: `defuddle-sidecar`. Don't merge until defuddle can reliably handle both websites and arXiv HTML papers.

## What's done

- Defuddle sidecar service (`docker/defuddle/`) — Fastify + JSDOM, `POST /extract`, `GET /health`
- Dockerfile (`docker/Dockerfile.defuddle`) — two-stage node:22-slim build
- Docker Compose (base, dev port 8085, prod)
- Python client (`yapit/gateway/document/defuddle.py`) — 503 on sidecar unreachable
- `website.py` calls defuddle instead of trafilatura; JS detection + Playwright unchanged
- Config: `defuddle_url` in Settings + all .env files
- CI: build-defuddle job + paths-filter
- Deps: trafilatura + html2text removed from pyproject.toml
- Custom JSDOM instance without `resources: 'usable'` (prevents external CSS fetch timeouts)
- Bumped to defuddle 0.9.0
- Comparison tooling: `experiments/compare_extractors.py`

## Discovered issues

### Blocking

**Event loop blocking on math-heavy pages**: Paper 2510.08814 (837 `<math>` elements, 91 tables) locks up the entire Node.js process indefinitely. Health endpoint becomes unresponsive. Single-threaded Node.js means one bad request kills the sidecar for all users.

**One arXiv paper still times out on 0.9.0**: Same paper above. 7/8 papers with HTML now extract successfully (3 were complete failures on 0.8.0, fixed by 0.9.0 scoring improvements). But 100% reliability is needed.

**Sidecar concurrency model**: Current single-threaded Fastify server can't handle concurrent users — one slow parse blocks everything. Needs either: worker threads / cluster mode for CPU-bound parsing, multiple replicas behind the compose service, or an async architecture that doesn't block the event loop. Must handle dozens of concurrent users comfortably. Server-side timeout is the minimum safety net, but the concurrency model is the real fix.

### Non-blocking (quality)

**Display equations**: `ltx_eqn_table` elements with MathML render as raw `<table>` HTML instead of LaTeX `$$` blocks. Defuddle's `handleNestedEquations` function exists but doesn't match all arXiv equation table patterns. Tables aren't read by TTS (non-prose blocks) but they render visually.

**`<sup>` tag leakage**: Author affiliations and some footnote marks appear as raw `<sup>` HTML tags instead of being converted. Mechanically strippable in post-processing.

**Double figure captions**: "Figure 1: Figure 1: ..." — defuddle duplicates the label.

**Nav TOC included as content**: arXiv HTML navigation/table of contents included at the top of extraction. Strippable.

**`- •` double bullets**: List items with both markdown dash and HTML bullet character.

## Assumptions

- Defuddle upstream will continue improving arXiv/LaTeXML support — kepano is responsive (footnote issue fixed within a day), ~40 commits in 2 days, already has `ltx_*` class handling in codebase.
- We file well-scoped issues upstream rather than forking. Only fork if upstream explicitly declines to support something we need.
- PyMuPDF free path is adequate for the ~26% of arXiv papers without HTML. Quality won't match HTML extraction but it's the existing fallback.
- Performance issues are solvable — server-side timeout protects prod, upstream can fix the O(n²) math processing.

## Upstream coordination

Defuddle repo: `kepano/defuddle`. Currently on 0.9.0, HEAD is 10 commits ahead (sidenotes, table layout detection, whitespace handling).

**To file** (after building minimal repros):
- Performance: event loop blocking on math-heavy arXiv HTML (include the 2510.08814 HTML or a minimal reduction)
- arXiv equation tables: `ltx_eqn_table` not caught by `handleNestedEquations` for all patterns
- Consider: high-level "arXiv HTML support" umbrella issue covering the quality items above

**Already addressed upstream**:
- Generic footnote detection fallback (our antikythera.org issue) — fixed in 0.9.0
- XSS in schema fallback — fixed in 0.9.0

## Done when

- [ ] Server-side timeout in sidecar (kill parse after N seconds, return 504)
- [ ] All 9 test arXiv papers extract without timeout or failure
- [ ] Upstream issues filed with minimal repros
- [ ] arXiv routing: check HTML availability, route to defuddle or PyMuPDF
- [ ] Website corpus validated end-to-end through the actual app (not just sidecar)
- [ ] markxiv service removed (compose, CI, Python client)
- [ ] Branch merged to main

## Considered & rejected

- **Subprocess call to defuddle CLI** — Node.js cold start per call (~200-400ms overhead). Sidecar is warmer and consistent with markxiv pattern.
- **Merging website-only now, arXiv later** — Adds complexity of shipping a partially-complete migration. Defuddle isn't production-hardened yet (the event loop blocking proves this). Wait until it's solid.
- **Forking defuddle for our own patches** — Upstream is extremely active and responsive. Filing issues is more effective than maintaining a fork. Revisit if upstream declines something critical.

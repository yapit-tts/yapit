---
status: done
started: 2026-01-23
---

# Task: Markxiv Integration for arXiv Papers

## Intent

Integrate [markxiv](https://github.com/tonydavis629/markxiv) as a free-tier document processor for arXiv papers. When users submit arXiv URLs and choose free processing (not AI transform), use markxiv instead of MarkItDown for higher quality extraction.

Markxiv converts arXiv papers from LaTeX source to markdown via pandoc, with pdftotext fallback. This produces better output than MarkItDown's PDF extraction for academic papers.

## Assumptions

- Markxiv runs as a Docker sidecar service on the VPS
- 5-10GB disk cache is sufficient (covers most popular papers many times over)
- No TTS annotations needed for free tier (raw markdown is acceptable)
- Figures are stripped by markxiv (acceptable trade-off for free tier)
- If markxiv fails, we error to user (no MarkItDown fallback initially)

## Sources

**External docs:**
- MUST READ: [markxiv README](https://github.com/tonydavis629/markxiv) — architecture, endpoints, config
- Reference: arXiv API docs for metadata endpoint

**Key code files:**
- MUST READ: `yapit/gateway/api/v1/documents.py` — prepare/create flow, URL handling
- MUST READ: `yapit/gateway/document/markitdown.py` — current free-tier processor pattern
- Reference: `docker-compose.yml` — for adding markxiv service

**Knowledge files:**
- [[document-processing]] — how content becomes blocks

## Design

### URL Detection

Detect arXiv URLs in the prepare endpoint:

```python
ARXIV_PATTERNS = [
    (r"arxiv\.org/abs/([\d.]+v?\d*)", "abs"),           # arxiv.org/abs/1706.03762
    (r"arxiv\.org/pdf/([\d.]+v?\d*)", "pdf"),           # arxiv.org/pdf/1706.03762.pdf
    (r"alphaxiv\.org/abs/([\d.]+v?\d*)", "abs"),        # alphaxiv mirror
    (r"alphaxiv\.org/pdf/([\d.]+v?\d*)", "pdf"),        # alphaxiv mirror
    (r"ar5iv\.labs\.google\.com/abs/([\d.]+v?\d*)", "abs"),  # ar5iv HTML mirror
]
```

Note: Only `/abs/` and `/pdf/` paths for mirrors — other paths (e.g., alphaxiv `/overview`) go through normal website flow. ar5iv only has `/abs/` (it's an HTML rendering, no PDF).

### Flow Differentiation

**`/abs/` URLs** → Instant flow (like current text input):
- Detect arXiv pattern
- Fetch markdown from markxiv
- Create document immediately
- Redirect to `/listen/{id}`

**`/pdf/` URLs** → Metadata banner flow (like current document upload):
- Detect arXiv pattern
- Prepare: fetch metadata from arXiv API (title, authors, page count)
- Show metadata banner with "Create" button
- Create: fetch markdown from markxiv

### Markxiv Service

Docker sidecar configuration:

```yaml
markxiv:
  build:
    context: ./markxiv
    # or: image: ghcr.io/tonydavis629/markxiv:latest
  volumes:
    - markxiv-cache:/cache
  environment:
    - PORT=8080
    - MARKXIV_CACHE_CAP=500                      # in-memory LRU entries
    - MARKXIV_DISK_CACHE_CAP_BYTES=10737418240   # 10GB
    - MARKXIV_CACHE_DIR=/cache
  networks:
    - internal
```

Dependencies inside container: pandoc, poppler-utils (pdftotext)

### Integration Points

1. **URL detection** in `_download_document()` or new helper
2. **Prepare endpoint**: if arXiv detected, fetch metadata from arXiv API directly (not markxiv)
3. **Create endpoint**: if arXiv + free tier, call `http://markxiv:8080/abs/{id}` instead of MarkItDown
4. **Cache key**: use arXiv ID as content_hash for extraction cache deduplication

### arXiv Metadata Fetch

For prepare step, fetch from arXiv API directly (faster than full markxiv conversion):

```python
async def fetch_arxiv_metadata(arxiv_id: str) -> DocumentMetadata:
    url = f"https://export.arxiv.org/api/query?id_list={arxiv_id}"
    # Parse Atom XML for title, authors, summary
    # Return DocumentMetadata with estimated page count (abstract length heuristic or just 1)
```

### Error Handling

- markxiv 404 → "Paper not found on arXiv"
- markxiv 422 → "Paper has no source available and PDF extraction failed"
- markxiv 502 → "Could not reach arXiv servers"
- markxiv 500 → "Paper conversion failed"

No fallback to MarkItDown initially — if markxiv can't handle it, the paper likely has issues.

## Done When

- [ ] markxiv running as Docker sidecar on VPS
- [ ] arXiv URLs detected in prepare endpoint
- [ ] `/abs/` URLs use instant flow
- [ ] `/pdf/` URLs use metadata banner flow
- [ ] alphaxiv.org URLs normalized to arxiv.org
- [ ] Free-tier arXiv processing uses markxiv instead of MarkItDown
- [ ] AI transform still available for arXiv (uses Gemini as before)
- [ ] Error messages are user-friendly

## Considered & Rejected

**Library integration instead of sidecar**: Could port markxiv logic to Python, but:
- Rust binary is fast and battle-tested
- Sidecar is cleaner separation
- markxiv has its own caching that "just works"

**MarkItDown fallback on markxiv failure**: Deferred. If markxiv fails, the paper usually has issues (no source, complex macros). Can add fallback later if we see common failures.

## Discussion

- Cache sizing: 10GB disk cache covers ~2M papers worth of gzipped markdown. arXiv has ~2.4M papers total, but access follows power law — 10GB easily covers the hot set.
- alphaxiv.org: Only `/abs/` and `/pdf/` paths redirect to markxiv. Other paths (like `/overview`) go through normal website processing.
- No TTS annotations: Free tier gets raw LaTeX math (`$\alpha$`), not spoken alternatives. This is acceptable trade-off.

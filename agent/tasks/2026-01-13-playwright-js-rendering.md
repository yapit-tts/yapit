---
status: active
started: 2026-01-13
---

# Task: Robust URL Fetching (Playwright + Error Handling)

## Intent

Improve URL fetching robustness:
1. **JS-rendered pages** — Support sites like `https://www.k-a.in/DDL.html` that load content dynamically via JavaScript
2. **Better error messages** — User-friendly errors for HTTP failures, not just "HTTP 4xx"
3. **Content protection** — Detect and clearly communicate Cloudflare challenges, paywalls, login walls
4. **Content-type reliability** — Don't trust headers blindly, verify with magic bytes

User wants this to be scalable and free (no external APIs). Solution: Playwright headless browser with lazy loading + improved error handling.

## Background

**The problematic page:**
- Static HTML has: header image, title, author link (~200 chars after conversion)
- JavaScript fetches `DDL.md` and renders it with marked.js
- Full content: 15,516 chars of markdown (math-heavy ML article)

**Current flow** (`documents.py`):
1. `_download_document()` (line 652-707) - httpx GET, returns raw HTML
2. `create_website_document()` (line 290-348) - MarkItDown converts HTML → markdown
3. No JavaScript execution → minimal content

**Verified fix:**
```python
# Playwright renders full content
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(url, wait_until='networkidle')
    html = page.content()  # 255KB rendered HTML
```
Then MarkItDown produces 15,516 chars instead of ~200.

## Assumptions

- Playwright adds ~110MB to Docker image (Chromium headless shell)
- Rendering takes 2-5 seconds per page (acceptable for infrequent JS sites)
- Memory: ~50MB per page with browser pooling (single browser instance reused)
- Most sites don't need JS rendering - only trigger when needed
- Semaphore limits concurrent renders to bound memory usage

## Sources

**Knowledge files:**
- [[document-processing]] — Core flow from URL to StructuredDocument

**Key code files:**
- `yapit/gateway/api/v1/documents.py:652-707` — `_download_document()`
- `yapit/gateway/api/v1/documents.py:290-348` — `create_website_document()`
- `yapit/gateway/processors/document/markitdown.py` — MarkItDown wrapper
- `yapit/gateway/Dockerfile` — Needs browser deps + install step

**External docs:**
- Reference: [Playwright Python async](https://playwright.dev/python/docs/library#async-playwright)

## Done When

- [x] JS-rendered pages like k-a.in/DDL.html produce full content
- [x] Static sites remain fast (no Playwright overhead)
- [x] Docker image builds with Playwright browser
- [x] No external API dependencies
- [x] HTTP errors show user-friendly messages (not just "HTTP 4xx")
- [x] Content-type sniffing handles misconfigured servers
- [ ] ~~Cloudflare/paywall detection~~ — Skipped: blocking doesn't add value without ability to circumvent

## Implementation Plan

### 1. Add Playwright dependency

```bash
uv add playwright
```
Then pin version in pyproject.toml with `~=` constraint.

### 2. Create renderer module

`yapit/gateway/processors/document/playwright_renderer.py`:
- Lazy-load playwright on first use (avoid import cost for normal requests)
- Browser pooling: single browser instance, new page per request (~50MB/page vs ~300MB/browser)
- Async function that renders URL and returns HTML
- Handles timeout, errors gracefully

**Memory management:** Semaphore at 100 concurrent renders as defense in depth. Log warning when semaphore is full (signals abnormal patterns). VPS has 18GB available, so 100 × 50MB = 5GB is comfortable. Threshold high enough to never affect normal operation.

### 3. Detection: when to use Playwright

**Combined approach** (content sniffing + size heuristic):

1. **Content sniffing** — detect known JS rendering patterns in HTML:
   - `marked.parse`, `markdown-it`, `renderMarkdown` (markdown renderers)
   - `ReactDOM`, `createApp(`, `ng-app` (SPA frameworks)
   - Catches the *cause*

2. **Size heuristic** — small output from big input:
   - Large HTML (>5KB) but tiny markdown (<500 chars)
   - Catches the *symptom* (works for unknown/custom patterns)

**Combined logic:** Trigger Playwright if EITHER detects JS rendering.

| Scenario | Content sniff | Size heuristic | Combined |
|----------|---------------|----------------|----------|
| k-a.in (marked.js) | ✅ | ✅ | ✅ |
| React SPA with big static nav | ✅ | ❌ | ✅ |
| Obscure custom JS loader | ❌ | ✅ | ✅ |
| Normal static site | ❌ | ❌ | ❌ |

Content sniffing is cheap (regex on HTML we already have). False positives (SSR page with React import) just waste ~2-3 seconds - acceptable.

### 4. Update Dockerfile

- Install Chromium system dependencies (libnss3, libatk, etc.)
- Run `playwright install chromium` after pip install
- Adds ~110MB to image size

### 5. HTTP Error Messages

Improve error messages in `_download_document()` for common status codes:

| Status | Current | Better |
|--------|---------|--------|
| 300 | "HTTP 300" | "Document has multiple versions - try a more specific URL" |
| 401 | "HTTP 401" | "This page requires authentication" |
| 403 | "HTTP 403" | "Access to this page is forbidden" |
| 404 | "HTTP 404" | "Page not found - check the URL" |
| 429 | "HTTP 429" | "Site is rate limiting requests - try again later" |
| 451 | "HTTP 451" | "Content unavailable for legal reasons" |
| 500-504 | "HTTP 5xx" | "The website is having issues - try again later" |

### 6. Content-Type Sniffing

Don't trust `Content-Type` header blindly. Verify with magic bytes:

| Type | Magic bytes |
|------|-------------|
| PDF | `%PDF` |
| PNG | `\x89PNG` |
| JPEG | `\xFF\xD8\xFF` |
| HTML | `<!DOCTYPE` or `<html` |

If header and content mismatch, trust actual content. Adds robustness against misconfigured servers.

### 7. Testing

1. Test with k-a.in/DDL.html - should produce full content ✅
2. Test with static site (news article) - should remain fast, no Playwright triggered
3. Test edge cases: timeouts, failed renders, concurrent requests
4. Test HTTP error cases - verify user-friendly messages
5. Test bioRxiv PDF links - see if Playwright passes simple Cloudflare challenges

## Considered & Rejected

**Jina Reader API:**
- External dependency, rate limits
- User wants scalable free solution

**Pattern detection (fetch DDL.md directly):**
- Only works for this specific blog pattern
- Most JS sites use React/Vue with JSON APIs

**Always use Playwright:**
- 2-5 second overhead for ALL pages
- Unnecessary for static sites (99% of cases)

## Open Questions

- Exact threshold values (500 chars, 5KB HTML) — may need tuning based on real-world pages.
- Which JS patterns to sniff for — start with common ones (marked, React, Vue, Angular), expand based on missed cases.

## Discussion

User chose Playwright over Jina Reader because:
1. No external API dependency
2. Scalable without rate limits
3. Keeps free tier truly free
4. ~110MB image size increase is acceptable

**Memory/semaphore decision:** VPS has 18GB available. Semaphore at 100 is cheap insurance — won't trigger in normal operation, but prevents crash under abnormal load and logs a warning for visibility. Cost is ~5 lines of code, no real downside at this threshold.

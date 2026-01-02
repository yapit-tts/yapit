---
status: active
type: research
---

# Task: XSS Security Audit for HTML Document Display

## Goal

Audit input-related security vulnerabilities:
1. **XSS**: How we display HTML content from websites - are we protected against XSS attacks?
2. **SSRF**: When fetching URLs, could we be tricked into hitting internal services?
3. **File uploads**: Path traversal, malware concerns

## Notes / Findings

### 1. XSS Analysis

**Risk Level: MEDIUM** (mitigated for website flow, but direct text input is vulnerable)

#### Data Flow

```
Website URL → MarkItDown → markdown → parse_markdown() → AST → transform_to_document() → HTML blocks → dangerouslySetInnerHTML
Direct Text → parse_markdown() → AST → transform_to_document() → HTML blocks → dangerouslySetInnerHTML
```

#### Key Findings

**MarkItDown (website flow) provides some protection:**
- Script tags are stripped: `<script>alert(1)</script>` → not present in markdown output
- Event handlers stripped: `onclick`, `onerror` not preserved
- `javascript:` URLs in links are stripped

**BUT the direct text input path is vulnerable:**
- Users can paste markdown with raw HTML
- markdown-it in CommonMark mode parses raw HTML as `html_block` and `html_inline` nodes
- The transformer (`transformer.py`) handles `html_inline` by converting to `TextContent` without escaping
- `_render_inline_content_html` returns text content raw: `return node.content` (no HTML escaping)
- Frontend uses `dangerouslySetInnerHTML` in 6+ places (`structuredDocument.tsx` lines 176, 193, 211, 313, 325, 425)

**Attack scenario:**
1. User pastes text containing: `Hello <script>alert(1)</script> world`
2. markdown-it parses this as: text + html_inline(`<script>`) + text(`alert(1)`) + html_inline(`</script>`) + text
3. Transformer converts html_inline to TextContent with raw content
4. Rendered HTML: `Hello <script>alert(1)</script> world`
5. Frontend inserts via dangerouslySetInnerHTML → XSS

**Verified safe:**
- `javascript:` URLs in markdown links are blocked by markdown-it (CommonMark mode)
- Images with `javascript:` src would need to go through img tag rendering

### 2. SSRF Analysis

**Risk Level: LOW-MEDIUM** (requires open redirect on external site)

**Vulnerable code:** `_download_document()` in `documents.py:474-524`

```python
async with httpx.AsyncClient(follow_redirects=True, timeout=30.0, headers=headers) as client:
    response = await client.get(str(url))
```

**Issues:**
- `follow_redirects=True` - will follow redirects to any destination
- No validation of redirect destination against private IP ranges
- Pydantic's `HttpUrl` only validates initial URL is http/https

**Internal services accessible via Docker network (dokploy-network):**

*Yapit services:*
- `http://postgres:5432` - PostgreSQL (limited impact - HTTP to postgres)
- `http://redis:6379` - Redis (potential data exfil/manipulation via HTTP smuggling)
- `http://stack-auth:8101` - Auth dashboard
- `http://stack-auth:8102` - Auth API
- `http://gateway:8000` - API gateway itself
- `http://frontend:80` - Nginx frontend
- `http://kokoro-cpu:...` - TTS workers

*Dokploy infrastructure:*
- `http://traefik:80` / `http://traefik:443` - Reverse proxy
- `http://dokploy:3000` - Dokploy web interface (if on same network)
- Port 4500 - Monitoring metrics

*Cloud metadata (if deployed on cloud):*
- `http://169.254.169.254/` - AWS/GCP/Azure instance metadata

**Attack scenario:**
1. Attacker hosts `https://evil.com/redirect` that 302 redirects to `http://stack-auth:8102/api/...`
2. User submits `https://evil.com/redirect` as document URL
3. Gateway follows redirect, hits internal auth service
4. Response content potentially leaked to attacker via document content

**Mitigating factors:**
- Requires attacker to control a domain that redirects
- Response must be parseable by MarkItDown
- Attacker doesn't see raw response, only processed markdown

### 3. File Upload Analysis

**Risk Level: LOW**

**Findings:**
- Files stored by content hash, not filename: `cache_key = hashlib.sha256(content).hexdigest()`
- No filesystem writes using user-supplied filename
- `file.filename` stored in metadata only, not used for paths
- Content stored in Redis cache, not filesystem

**No path traversal vulnerability** - filenames are metadata only.

**Malware concerns:**
- PDF/DOCX parsing uses external libraries (pymupdf, MarkItDown)
- These could theoretically be exploited via malformed files
- But this is defense-in-depth territory, not a direct vulnerability

## Recommendations

### XSS Fix (Priority: HIGH)

**Option A: Frontend sanitization with DOMPurify** (Recommended)
- Add DOMPurify to frontend: `npm install dompurify @types/dompurify`
- Sanitize all HTML before dangerouslySetInnerHTML:
  ```tsx
  import DOMPurify from 'dompurify';
  dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(block.html) }}
  ```
- Pros: Defense in depth, catches any backend bugs
- Cons: Small bundle size increase (~7KB gzipped)

**Option B: Backend HTML escaping in transformer**
- Escape HTML entities in `_render_inline_content_html` for text nodes
- Strip `html_inline` and `html_block` nodes entirely
- Pros: No frontend dependency
- Cons: Loses legitimate HTML formatting users might want

**Option C: Disable raw HTML in markdown-it**
- Configure markdown-it with `html: false`
- Pros: Simple config change
- Cons: May break legitimate use cases, doesn't protect against other injection vectors

**Recommendation:** Use Option A (DOMPurify) as primary defense. It's the most robust and handles edge cases we haven't thought of.

### SSRF Fix (Priority: MEDIUM)

**Option A: Validate redirect destinations** (Recommended)
- Before following redirects, check destination against blocklist
- Block private IP ranges: `127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `169.254.0.0/16`
- Block internal Docker hostnames: `postgres`, `redis`, `stack-auth`, `gateway`, `frontend`, `kokoro-cpu`, `traefik`, `dokploy`, `localhost`
- Still follows legitimate redirects (www→non-www, http→https, URL shorteners)

**Option B: Disable redirect following**
- Set `follow_redirects=False` in httpx client
- Simpler but may break legitimate sites that redirect (e.g., www → non-www)

**Option C: Use allowlist of content types**
- Only process responses with expected content types (text/html, application/pdf, etc.)
- Combined with option A for defense in depth

**Recommendation:** Option A - validate redirect destinations. This is the standard approach for SSRF prevention.

### File Uploads (Priority: LOW)

No immediate action needed. Current implementation is safe from path traversal.

For defense in depth (future):
- Consider running document processors in sandboxed environment
- Add virus scanning for uploaded files (ClamAV or cloud service)

## Open Questions

1. **For XSS fix:** Should we allow ANY raw HTML in user input, or strip it entirely? DOMPurify can be configured to allow safe subset (e.g., `<b>`, `<i>`) or strip all tags. **Default recommendation:** Use DOMPurify's default config which keeps safe formatting tags.

~~2. **For SSRF fix:** Do we need to support sites that require redirects?~~ **Answered:** Yes, support redirects with destination validation.

---

## Work Log

### 2025-12-29 - Task Created

Created from architecture.md todolist item. Ready for investigation.

### 2025-12-31 - Security Audit Complete

**Investigation performed:**

Files read:
- `yapit/gateway/processors/document/markitdown.py` - MarkItDown wrapper, no sanitization logic
- `yapit/gateway/api/v1/documents.py` - URL fetching with SSRF risk, file upload handling
- `yapit/gateway/processors/markdown/parser.py` - markdown-it-py parser config
- `yapit/gateway/processors/markdown/transformer.py` - HTML generation from AST, no escaping
- `frontend/src/components/structuredDocument.tsx` - 6 uses of dangerouslySetInnerHTML
- `docker-compose.yml`, `docker-compose.dev.yml` - internal service topology

Testing performed:
- Verified MarkItDown strips script tags and event handlers from HTML
- Verified markdown-it passes raw HTML through as `html_block`/`html_inline` nodes
- Verified transformer doesn't escape HTML entities in text content
- Verified no DOMPurify or sanitization in frontend

**Summary:**
- XSS via direct text input: VULNERABLE (user can paste raw HTML in markdown)
- XSS via website URL: MITIGATED (MarkItDown strips dangerous content)
- SSRF: VULNERABLE (redirect following without destination validation)
- Path traversal: NOT VULNERABLE (files stored by hash, not filename)

**Next steps:**
- Discuss with user which fix options to implement
- Implement chosen fixes

### 2025-12-31 - Clarifications and Scope Finalized

User asked clarifying questions, answered:

1. **iframe/object/embed:** Legacy embedding tags. Not used in current flow (MarkItDown strips them, transformer doesn't generate them). No loss from blocking.

2. **style tags:** Can enable CSS injection attacks (data exfiltration, UI redressing). DOMPurify strips by default. We don't need user-provided CSS, so no loss.

3. **SSRF redirects:** User confirmed we should support legitimate redirects (www→non-www, http→https). Will use destination validation approach.

4. **Dokploy context:** Updated blocklist to include all services on dokploy-network:
   - Yapit: postgres, redis, stack-auth, gateway, frontend, kokoro-cpu
   - Dokploy: traefik, dokploy (port 3000), monitoring (port 4500)

**Decisions made:**
- XSS: Use DOMPurify with default config (keeps safe formatting)
- SSRF: Validate redirect destinations (block private IPs + internal hostnames)

**Ready to implement.**

### 2025-12-31 - XSS Fix Implemented

Implemented DOMPurify fix for XSS vulnerability.

**Changes:**
- Added `dompurify` and `@types/dompurify` to frontend dependencies
- Created `sanitize()` wrapper function in `structuredDocument.tsx`
- Applied sanitization to all 6 `dangerouslySetInnerHTML` usages

**Commit:** `5c87e99 fix: add DOMPurify to sanitize HTML and prevent XSS attacks`

**Remaining:**
- SSRF fix (backend) - blocked on backend refactor completion

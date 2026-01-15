---
status: done
type: research
completed: 2025-01-06
---

# Task: XSS Security Audit for HTML Document Display

## Goal

Audit input-related security vulnerabilities:
1. **XSS**: How we display HTML content from websites - are we protected against XSS attacks?
2. **SSRF**: When fetching URLs, could we be tricked into hitting internal services?
3. **File uploads**: Path traversal, malware concerns

## Current Status

- **XSS: ✅ FIXED** - DOMPurify implemented (commit `5c87e99`)
- **SSRF: ✅ FIXED** - Smokescreen proxy implemented (2025-01-06)
- **File uploads: ✅ NO ACTION NEEDED** - Already safe

## Implementation Summary

**SSRF fix (2025-01-06):**
- Reverted broken application-level IP validation code
- Added Smokescreen proxy container (built from pinned commit `a7fdfcb5`)
- Configured httpx to route through `http://smokescreen:4750`
- Added to CI build matrix for ghcr.io
- 407 responses from proxy return user-friendly "URL points to a blocked destination"

Files changed:
- `docker/Dockerfile.smokescreen` - new
- `docker-compose.yml` - added smokescreen service
- `docker-compose.prod.yml` - added smokescreen service
- `.github/workflows/deploy.yml` - added to build matrix
- `yapit/gateway/api/v1/documents.py` - proxy config + error handling

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

**Risk Level: HIGH** - trivially exploitable, could give attacker access to internal services including auth

**Vulnerable code:** `_download_document()` in `documents.py`

**The vulnerability:**
- URL fetching follows redirects without validating destinations
- Attacker can redirect to internal Docker services or cloud metadata

**Internal services accessible via Docker network (yapit-network):**
- `http://stack-auth:8102` - **Auth API** (most dangerous - could read/modify users, create admins)
- `http://redis:6379` - Redis cache
- `http://postgres:5432` - Database
- `http://gateway:8000`, `http://frontend:80`, `http://kokoro-cpu:...`

**Why this is HIGH severity:**
- Account creation is trivial (no barrier to "authenticated" attacker)
- Attacker controls the URL they submit
- Attacker can set up DNS rebinding infrastructure in ~10 minutes
- If `stack-auth:8102` trusts internal callers (common for microservices), attacker could:
  - Read/modify user data
  - Create admin accounts
  - Access API keys or secrets
  - Pivot to database access

**DNS Rebinding Attack (bypasses application-level IP validation):**
1. Attacker controls `evil.com` with TTL=0
2. First DNS resolution returns `1.2.3.4` (public IP) → passes validation
3. Application validates and proceeds
4. Attacker flips DNS to `169.254.169.254` or `172.17.0.x`
5. HTTP client resolves again for actual connection → gets internal IP
6. Request hits internal service

The window between validation and connection is easily tens to hundreds of milliseconds - plenty of time for DNS flip.

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

### SSRF Fix (Priority: HIGH - CRITICAL)

**Why application-level validation is insufficient:**
Any approach that validates DNS/IP before the HTTP request has a TOCTOU (time-of-check-time-of-use) vulnerability. DNS rebinding attacks exploit the gap between validation and connection.

**Rejected approaches:**
1. **Hostname blocklist + IP validation before request** - Bypassable via DNS rebinding
2. **Custom httpx transport with IP pinning** - Complex, error-prone, TLS SNI issues
3. **Disable TLS verification to connect to IPs directly** - Worse (enables MITM)

**Chosen solution: Smokescreen proxy (Stripe)**
- https://github.com/stripe/smokescreen
- HTTP CONNECT proxy that validates at the network/connection layer
- DNS resolution and IP validation happen atomically at connect time
- Battle-tested by Stripe, handles edge cases
- Docker image available: `pretix/smokescreen`

**Implementation:**
1. Add Smokescreen container to docker-compose (listens on port 4750)
2. Configure httpx to use it as proxy: `httpx.AsyncClient(proxy="http://smokescreen:4750")`
3. Default behavior blocks private IP ranges - no config needed for our use case

**Why Smokescreen is better:**
- Network-layer validation can't be raced (no TOCTOU)
- Handles all edge cases (DNS rebinding, redirects, etc.)
- ~10 lines of config vs 100+ lines of complex custom code
- All normal URLs still work, only internal/private blocked

### File Uploads (Priority: LOW)

No immediate action needed. Current implementation is safe from path traversal.

For defense in depth (future):
- Consider running document processors in sandboxed environment
- Add virus scanning for uploaded files (ClamAV or cloud service)

## Open Questions

All questions resolved. See work log for decisions.

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
- ~~SSRF fix (backend) - blocked on backend refactor completion~~

### 2025-01-06 - SSRF Analysis Deep Dive and Solution Selection

**Initial attempt: Application-level IP validation**

Implemented DNS resolution + IP validation in `_download_document()`:
- Added `_PRIVATE_IP_RANGES` tuple
- Added `_resolve_and_validate_url()` function
- Modified `_download_document()` to validate before each request

**User challenged the approach - correctly identified DNS rebinding vulnerability:**

The initial code had a TOCTOU gap:
1. Our code resolves DNS, validates IP is public → passes
2. httpx internally resolves DNS again for the actual connection
3. Attacker can flip DNS between these two resolutions (TTL=0)
4. Connection goes to internal IP despite validation passing

User's key points:
- "Authentication is no barrier" - account creation is trivial
- "Motivated attacker" is meaningless - automated tools exist
- Code is public - anyone can find and exploit this
- DNS rebinding servers take ~10 minutes to set up (tools like `rebinder`)
- Stack-auth likely trusts internal callers → full auth system compromise possible

**Attempted fix: Connect to resolved IP directly**

Tried modifying code to connect to the resolved IP with Host header for virtual hosting. Problem: TLS certificate verification. Either:
- `verify=False` → enables MITM attacks (worse than the original problem)
- Custom SSL context with SNI → complex, error-prone

**Final decision: Use Smokescreen proxy**

After evaluating options:
1. ~~Application-level validation~~ - Bypassable via DNS rebinding
2. ~~Custom httpx transport~~ - Complex, TLS issues
3. ~~iptables on host~~ - Would break Docker internal networking
4. ~~Separate fetcher microservice~~ - Architectural overhead
5. **Smokescreen proxy** ✓ - Network-layer validation, battle-tested

Smokescreen (https://github.com/stripe/smokescreen):
- Built by Stripe specifically for SSRF protection
- Validates at connection layer (no TOCTOU possible)
- Docker image: `pretix/smokescreen`
- Default config blocks private IPs - exactly what we need

**Current state of code: MESSY - NEEDS CLEANUP**

`documents.py` has incomplete/incorrect SSRF code that needs to be:
1. Removed (the `_resolve_and_validate_url`, `_PRIVATE_IP_RANGES` stuff)
2. Replaced with Smokescreen proxy configuration

The current code in `documents.py` is NOT a valid fix and should not be deployed.

**XSS fix status: COMPLETE**
- DOMPurify implemented and committed: `5c87e99`
- This fix is solid and can be deployed

**SSRF fix status: NOT COMPLETE**
- Need to: add Smokescreen to docker-compose, configure httpx to use proxy
- Current code in documents.py is broken/incomplete - revert or clean up

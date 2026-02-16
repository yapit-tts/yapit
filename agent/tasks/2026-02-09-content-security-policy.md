---
status: active
started: 2026-02-09
---

# Task: Add Content Security Policy (CSP) Header

## Intent

Add CSP header to harden against XSS bypass/escalation, data exfiltration, and malicious resource loading. DOMPurify is already in place for XSS — CSP is the defense-in-depth layer.

## Assumptions

- CSP can break things if misconfigured (inline styles, data URIs in sanitized HTML, external fonts/scripts)
- Need to inventory everything the page loads before writing the policy
- Can start with report-only mode (`Content-Security-Policy-Report-Only`) to detect violations without breaking anything

## Why It's Its Own Task

CSP requires careful testing. Unlike X-Frame-Options or HSTS (which are set-and-forget), CSP needs an inventory of all resource origins, inline usage patterns, and testing across all page types. Getting it wrong either breaks the app or provides false security.

## Approach

1. Audit what the frontend loads: scripts, styles, images, fonts, WebSocket, API calls, external resources
2. Draft a policy based on the audit
3. Deploy with `Content-Security-Policy-Report-Only` first to catch violations
4. Monitor for breakage, then switch to enforcing mode

## Key Directives to Consider

- `default-src 'self'` — baseline
- `script-src 'self'` — no inline scripts (React doesn't need them with proper bundling)
- `style-src 'self' 'unsafe-inline'` — many React libs use inline styles, may need this
- `img-src 'self' data: https://images.yapit.md` — R2 CDN for extracted images
- `connect-src 'self' wss://yapit.md` — API + WebSocket
- `font-src 'self'` — if using self-hosted fonts
- `frame-ancestors 'none'` — replaces X-Frame-Options
- `form-action 'self'` — form submission targets

## Sources

**Knowledge files:**
- [[security]] — existing security patterns
- [[frontend]] — component architecture, what gets loaded

**External docs:**
- MUST READ: [MDN CSP guide](https://developer.mozilla.org/en-US/docs/Web/HTTP/CSP)
- Reference: [CSP Evaluator](https://csp-evaluator.withgoogle.com/) — validates policy strength

**Key code files:**
- MUST READ: `frontend/nginx.conf` — where the header will be added
- MUST READ: `frontend/src/components/structuredDocument.tsx` — DOMPurify + dangerouslySetInnerHTML usage
- Reference: `frontend/index.html` — check for inline scripts/styles

## Done When

- CSP header deployed in report-only mode
- No violations observed in normal usage
- Switched to enforcing mode

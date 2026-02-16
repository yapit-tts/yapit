# Security

## Audits

- [[xss-security-audit]] — XSS and SSRF analysis, DOMPurify, Smokescreen proxy
- [[beta-launch-security-checklist]] — CORS, CSP, secrets, SQL injection, CSRF, auth gaps, deps, HTTPS, error leakage, SSRF

## Patterns

- SSRF protection via Smokescreen proxy (network-layer, not application-level IP validation)
- Frontend renders from inline AST (no `dangerouslySetInnerHTML`), raw `html_inline` nodes dropped in transformer
- File uploads stored by content hash, not user-supplied filename
- Security headers set in `frontend/nginx.conf`: HSTS, X-Frame-Options DENY, X-Content-Type-Options nosniff, Referrer-Policy

## Gotchas

- **nginx `add_header` inheritance** — If a `location` block has ANY `add_header`, it stops inheriting ALL server-level `add_header` directives. Security headers must be repeated in every location block that has its own `add_header` (e.g., cache-control blocks). Auth proxy locations (`/auth/api/`, `/auth/`) must NOT get `X-Frame-Options DENY` — Stack Auth uses iframes for token refresh.

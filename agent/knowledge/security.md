# Security

## Audits

- [[xss-security-audit]] — XSS and SSRF analysis, DOMPurify, Smokescreen proxy

## Patterns

- SSRF protection via Smokescreen proxy (network-layer, not application-level IP validation)
- HTML sanitization via DOMPurify in frontend
- File uploads stored by content hash, not user-supplied filename

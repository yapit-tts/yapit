---
status: active
type: research
---

# Task: Beta Launch Security Checklist

## Goal

Security audit for infrastructure, auth, and configuration before launching to beta testers (friends). Complements [[xss-security-audit]].

## Checklist

### 1. CORS Configuration
- [ ] Verify CORS origins are restricted to our domains only
- [ ] Check `allow_credentials` setting
- [ ] Ensure no wildcard (`*`) in production

**Files to check:** `yapit/gateway/main.py` or wherever FastAPI CORS middleware is configured

### 2. Content Security Policy (CSP)
- [ ] Check if CSP headers are set
- [ ] If not, determine if we need them (blocks inline scripts, mitigates XSS)
- [ ] Consider adding via nginx/Traefik or FastAPI middleware

**Note:** CSP can break things if misconfigured. Test thoroughly.

### 3. Secrets in Code/Logs
- [ ] Grep for hardcoded secrets, API keys, passwords
- [ ] Check logging doesn't include sensitive data (tokens, passwords, API keys)
- [ ] Verify `.env` files are gitignored
- [ ] Check error responses don't leak internal details

**Commands:**
```bash
# Check for hardcoded secrets
rg -i "(password|secret|api.?key|token)\s*=" --type py --type ts
# Check logging statements
rg "logger\.(info|debug|error|warning)" --type py -A 2
```

### 4. SQL Injection
- [ ] Verify all DB queries use SQLAlchemy ORM (not raw SQL)
- [ ] Check for any `text()` or raw SQL usage
- [ ] If raw SQL exists, verify parameterization

**Low risk** - SQLAlchemy ORM handles this, but worth verifying no raw queries.

### 5. CSRF Protection
- [ ] Verify token-based auth (not cookies alone) for API endpoints
- [ ] Check if any endpoints use cookie-based auth that needs CSRF tokens

**Low risk** - We use Stack Auth with JWT tokens, not session cookies for API auth.

### 6. API Authorization Gaps
- [ ] Can user A access user B's documents?
- [ ] Can user A modify user B's data?
- [ ] Are admin endpoints properly protected?
- [ ] Test document CRUD with different user contexts

**Files to check:**
- `yapit/gateway/api/v1/documents.py` - document access control
- `yapit/gateway/deps.py` - auth dependencies
- `yapit/gateway/api/v1/admin.py` - admin endpoint protection

### 7. Dependency Audit
- [ ] Run `npm audit` on frontend
- [ ] Run `pip audit` or `safety check` on backend
- [ ] Review and address high/critical vulnerabilities

### 8. HTTPS Enforcement
- [ ] Verify all production traffic is HTTPS
- [ ] Check for mixed content (HTTP resources on HTTPS pages)
- [ ] Verify HSTS header is set (Strict-Transport-Security)
- [ ] Check WebSocket uses WSS (not WS) in production

### 9. Error Message Leakage
- [ ] Verify production doesn't expose stack traces
- [ ] Check exception handlers return safe error messages
- [ ] Ensure DB errors don't leak schema details
- [ ] Verify external API errors (Stack Auth, Mistral, RunPod) are sanitized

**Test by:** Triggering various errors and checking responses don't include internal details.

### 10. SSRF Redirect Validation (from XSS audit)
- [ ] Verify blocklist includes all internal services: `postgres`, `redis`, `stack-auth`, `localhost`
- [ ] Verify private IP ranges blocked: `127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `169.254.0.0/16`
- [ ] Test with actual redirect to blocked destination
- [ ] Update blocklist if docker-compose services changed

**Context:** [[xss-security-audit]] decided to allow redirects but block internal services. Need to verify implementation is complete and current.

## Notes / Findings

*To be populated during audit*

---

## Work Log

### 2025-12-31 - Task Created

Created as companion to `xss-security-audit.md` for beta launch preparation. Covers infrastructure, auth, and config security.

Items to audit:
1. CORS configuration
2. Content Security Policy
3. Secrets in code/logs
4. SQL injection (verify ORM usage)
5. CSRF (verify token-based auth)
6. API authorization gaps
7. Dependency audit (npm/pip)
8. HTTPS enforcement
9. Error message leakage
10. SSRF redirect validation (verify blocklist current)

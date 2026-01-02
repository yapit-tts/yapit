---
status: active
type: implementation
---

# Task: Migrate from yaptts.org to yapit.md

## Goal

Consolidate everything to the new yapit.md domain. Replace all occurrences of yaptts.org, update infrastructure config.

## Scope

### Code Changes
- [ ] Search codebase for `yaptts.org` occurrences
- [ ] Update any hardcoded domain references
- [ ] Update environment variables / .env files

### Infrastructure
- [ ] **Hetzner/Deploy**: Update server config to serve yapit.md
- [ ] **Caddy/nginx**: Update reverse proxy config for new domain
- [ ] **SSL certs**: Ensure certs issued for yapit.md
- [ ] **Stack Auth**: Update allowed origins / redirect URLs
- [ ] **Cloudflare** (if used): Update DNS / proxy settings

### Knowledge Files
- [ ] Update `agent/knowledge/architecture.md` if domain mentioned
- [ ] Update any other knowledge files with old domain

### Optional
- [ ] Set up yaptts.org → yapit.md redirect (if keeping old domain)
- [ ] Update GitHub repo description / links if applicable

## Notes

- Infrastructure is NOT fully IaC — some things may require UI changes
- Stack Auth config likely needs UI update for allowed domains
- Check deploy scripts for hardcoded references

## Work Log

### 2025-12-30 - Task Created

Domain yapit.md registered and DNS configured. Need to migrate all references from yaptts.org.

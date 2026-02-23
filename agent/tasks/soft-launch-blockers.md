---
status: done
type: tracking
started: 2026-01-05
---

# Soft Launch Blockers

## Goal

Get the product to a state where you can:
- Use production daily (not local dev) with persistent documents
- Trust auth, billing, data integrity
- Share promo codes with friends & family
- Not worry about DB resets or billing bugs embarrassing you

NOT public launch (HN, ToS, privacy policy, EU withdrawal). Just "10-20 friends can use this."

## Subtasks

### Schema Changes (Batch Into One Migration)

| Task | Status | Notes |
|------|--------|-------|
| [[admin-endpoints-and-soft-delete]] | ✅ DONE | `is_active` on TTSModel, Voice, DocumentProcessor |
| [[guest-to-registered-conversion]] | ✅ DONE | Claim endpoint + frontend flow |
| [[cross-device-sync]] | ✅ DONE | Playback position on Document, UserPreferences table |
| [[account-management]] | ✅ DONE | Deletion endpoint, user stats, settings page |

**Implementation note:** Schema changes from all four tasks should be batched into ONE migration. Backend endpoints can follow. Frontend work can be parallel or after endpoints.

### Security

| Task | Status | Notes |
|------|--------|-------|
| [[xss-security-audit]] | ✅ DONE | XSS (DOMPurify) + SSRF fix complete |
| [[beta-launch-security-checklist]] | 🔲 TODO | 10-item checklist |

### Billing & Auth

| Task | Status | Notes |
|------|--------|-------|
| [[stripe-testing-fresh-sandbox]] | 🔄 IN PROGRESS | E2E validation |
| [[oauth-providers-setup]] | ✅ DONE | GitHub + Google configured and tested |

### Ops

| Task | Status | Notes |
|------|--------|-------|
| [[hetzner-backups-restore]] | ✅ DONE | Documented in [[backup-rollback]] |
| [[self-hosting]] | 🔲 TODO | make target, docs, testing |
| Rollback strategy | ✅ DONE | Documented in [[backup-rollback]] |

## High-Level Decisions

- **Soft delete:** Only for system-managed entities (models, voices, processors). User data (docs, filters) hard deletes.
- **Anonymization on user deletion:** `user_id = "deleted-{hash}"` preserves patterns, fully anonymous.
- **Cross-device sync:** Block index + pinned voices only. Speed, selected voice, etc. stay local.
- **User stats source:** Postgres (Block.audio_duration_ms), not metrics SQLite.
- **Self-hosting:** Minimal effort — keep Stack Auth, keep seed, just add make target.

## Completion Criteria

- [x] Schema migration deployed
- [x] Guest claim endpoint working
- [x] Account deletion working
- [x] User stats page working
- [ ] Security checklist complete
- [x] SSRF fix deployed
- [x] OAuth tested in prod
- [ ] Stripe tested in prod
- [x] Backup/restore documented
- [x] Rollback documented
- [ ] Self-hosting documented + tested

## Public Launch Blockers (NOT soft launch)

- ~~[[stripe-eu-withdrawal]] — waiting on Stripe~~ ✅ resolved 2026-01-07, waiver language in ToS
- ~~Terms of Service~~ ✅ live at /terms (updated 2026-02-18)
- ~~Privacy Policy~~ ✅ live at /privacy (updated 2026-02-18)
- Per-endpoint rate limiting — in progress, see [[2026-02-21-endpoint-rate-limiting]]

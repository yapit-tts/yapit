---
status: active
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
| [[admin-endpoints-and-soft-delete]] | 🔲 TODO | `is_active` on TTSModel, Voice, DocumentProcessor |
| [[guest-to-registered-conversion]] | 🔲 TODO | Claim endpoint + frontend flow |
| [[cross-device-sync]] | 🔲 TODO | Playback position on Document, UserPreferences table |
| [[account-management]] | 🔲 TODO | Deletion endpoint, user stats, settings page |

**Implementation note:** Schema changes from all four tasks should be batched into ONE migration. Backend endpoints can follow. Frontend work can be parallel or after endpoints.

### Security

| Task | Status | Notes |
|------|--------|-------|
| [[xss-security-audit]] | ⚠️ PARTIAL | SSRF fix pending |
| [[beta-launch-security-checklist]] | 🔲 TODO | 10-item checklist |

### Billing & Auth

| Task | Status | Notes |
|------|--------|-------|
| [[stripe-testing-fresh-sandbox]] | 🔄 IN PROGRESS | E2E validation |
| [[oauth-providers-setup]] | ⚠️ PARTIAL | Configured, needs testing |

### Ops

| Task | Status | Notes |
|------|--------|-------|
| [[hetzner-backups-restore]] | 🔲 TODO | Backup/restore procedures |
| [[self-hosting]] | 🔲 TODO | make target, docs, testing |
| Rollback strategy | 🔲 TODO | Document procedure |

## High-Level Decisions

- **Soft delete:** Only for system-managed entities (models, voices, processors). User data (docs, filters) hard deletes.
- **Anonymization on user deletion:** `user_id = "deleted-{hash}"` preserves patterns, fully anonymous.
- **Cross-device sync:** Block index + pinned voices only. Speed, selected voice, etc. stay local.
- **User stats source:** Postgres (Block.audio_duration_ms), not metrics SQLite.
- **Self-hosting:** Minimal effort — keep Stack Auth, keep seed, just add make target.

## Completion Criteria

- [ ] Schema migration deployed
- [ ] Guest claim endpoint working
- [ ] Account deletion working
- [ ] User stats page working
- [ ] Security checklist complete
- [ ] SSRF fix deployed
- [ ] OAuth tested in prod
- [ ] Stripe tested in prod
- [ ] Backup/restore documented
- [ ] Rollback documented
- [ ] Self-hosting documented + tested

## Public Launch Blockers (NOT soft launch)

- [[stripe-eu-withdrawal]] — waiting on Stripe
- Terms of Service
- Privacy Policy
- rate-limiting

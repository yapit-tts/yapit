---
status: done
type: implementation
started: 2026-01-05
---

# Task: Soft Delete for System Entities

Parent: [[soft-launch-blockers]]

## Intent

Add `is_active` flag to system-managed entities so we can "retire" models/voices without breaking historical data. Can't hard-delete a Voice if BlockVariants reference it (FK constraint).

**Scope:** TTSModel, Voice, DocumentProcessor only. NOT for user-owned data (documents, filters — those hard delete).

## Implementation

### Schema Changes

Add to `domain_models.py`:

```python
# TTSModel
is_active: bool = Field(default=True, index=True)

# Voice
is_active: bool = Field(default=True, index=True)

# DocumentProcessor
is_active: bool = Field(default=True, index=True)
```

### Query Changes

Update queries to filter `WHERE is_active = true` for user-facing lists:
- Voice picker endpoint
- Model selection endpoint
- Processor selection (if exposed)

Historical lookups (e.g., "what voice was this BlockVariant?") do NOT filter — we want to show the voice even if retired.

### Migration

Batch with other schema changes from [[cross-device-sync]] and [[account-management]].

```bash
make migration-new MSG="add soft delete and user preferences"
```

## Sources

- `yapit/gateway/domain_models.py` — model definitions
- `yapit/gateway/api/v1/` — endpoints that query models/voices

## Admin Endpoints — Skipped

Not building admin endpoints or dashboard. Everything is handled by:
- **Model/voice/plan changes:** Migrations (version controlled)
- **Stripe config:** IaC script (version controlled)
- **User management:** Stack Auth dashboard
- **Subscription edge cases:** Stripe dashboard
- **Metrics:** Streamlit dashboard
- **Self-hosters:** Edit config files + restart

No use case for custom admin GUI. If this changes, revisit here.

---
status: active
type: implementation
---

# Task: Admin Endpoints & Soft Delete

## Goal

Implement proper data management for production:
1. Add `is_active` flag to models that need soft delete
2. Create admin endpoints OR establish migration-based workflow for data changes
3. Document how to create admin users via Stack Auth

## Context

**Problem:** Seed runs once on fresh DB. After launch, we need ways to:
- Add/remove TTS models
- Add/remove voices
- Update plans (not just prices)
- Manage document processors

**Constraint:** Can't hard delete models/voices if they have historical usage (BlockVariants reference TTSModel, Voice).

## Design Decision: Migrations vs Admin Endpoints

**Migrations (version-controlled, rollback-friendly):**
- Changes go through git, reviewed in PR
- Can rollback with `alembic downgrade`
- Audit trail via git history
- Requires deploy to apply changes

**Admin Endpoints (immediate, UI-driven):**
- Changes apply immediately via API/UI
- No git history for data changes
- Harder to rollback
- Good for frequent, minor changes

**Recommendation:** Start with migrations for model/plan changes (rare, significant). Consider admin endpoints later for frequent operations.

## Next Steps

1. Add `is_active: bool = True` to:
   - `TTSModel`
   - `Voice`
   - `DocumentProcessor`
   - (Plan already has `is_active`)

2. Update queries to filter `WHERE is_active = true` by default

3. Create migration for the new columns

4. Document admin user creation workflow

## Open Questions

1. **Which operations need admin endpoints vs migrations?**
   - Adding a new voice to existing model → migration? or admin endpoint?
   - Changing a voice's parameters → migration? or admin endpoint?

2. **Admin UI priority:**
   - Do we need an admin dashboard at all for launch?
   - Or just document "SSH + SQL" / "migration" workflows?

3. **Audit logging:**
   - Should admin actions be logged?
   - UsageLog exists but is for billing, not admin actions

## Notes / Findings

### Admin User Creation (Stack Auth)

Admin status comes from Stack Auth `server_metadata`:
```python
# deps.py:133
return bool(user.server_metadata and user.server_metadata.is_admin)
```

**To create admin user:**
1. User signs up normally
2. Go to Stack Auth dashboard (auth.yaptts.org or localhost:8101)
3. Find user → Edit → Set `server_metadata.is_admin = true`

Or via Stack Auth API:
```bash
curl -X PATCH "https://auth.yaptts.org/api/v1/users/{user_id}" \
  -H "x-stack-secret-server-key: $STACK_AUTH_SERVER_KEY" \
  -d '{"server_metadata": {"is_admin": true}}'
```

**TODO:** Verify this API call works. Document in knowledge file.

### Soft Delete Pattern

```python
class TTSModel(SQLModel, table=True):
    # ... existing fields ...
    is_active: bool = Field(default=True)

# In queries:
result = await db.exec(
    select(TTSModel).where(TTSModel.is_active == True)
)
```

For "deleted" models:
- Set `is_active = False`
- Model no longer appears in voice picker
- Historical BlockVariants still reference it (data preserved)
- Can "undelete" by setting `is_active = True`

---

## Work Log

### 2025-12-31 - Task Created

User raised important questions during seed refactor:
- How to add/remove models in production after initial seed?
- How to create admin accounts?
- Need soft delete for referential integrity

Decided: Create separate task rather than blocking seed refactor. Migrations preferred over admin endpoints for version control.

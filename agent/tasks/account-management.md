---
status: active
type: implementation
started: 2026-01-05
---

# Task: Account Management

Parent: [[soft-launch-blockers]]

## Intent

Users need a settings page where they can:
1. View their usage stats
2. Delete their account (GDPR compliance)
3. Change email/password (via Stack Auth)

Goal: "Idle business" — fully automated, no manual intervention needed.

## User Stats

### What to Show

- Total minutes synthesized (sum audio_duration_ms from user's Blocks)
- Total characters synthesized
- Breakdown by model (listening time per model)
- Document count
- Fun comparison: "That's equivalent to X Lord of the Rings trilogies"
  - Look up LOTR trilogy character count for implementation
  - Fits Ghibli/elvish vibe, not generic/corporate

### Data Source

Postgres only — don't query metrics SQLite for user-facing stats.

```sql
-- Total audio duration for user
SELECT SUM(b.audio_duration_ms)
FROM block b
JOIN document d ON b.document_id = d.id
WHERE d.user_id = :user_id;

-- By model
SELECT bv.model_slug, SUM(b.audio_duration_ms)
FROM block b
JOIN document d ON b.document_id = d.id
JOIN blockvariant bv ON bv.block_id = b.id
WHERE d.user_id = :user_id
GROUP BY bv.model_slug;
```

### Endpoint

`GET /v1/users/me/stats`

```python
@router.get("/users/me/stats")
async def get_user_stats(user: User = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    # Total audio duration
    total_ms = await db.exec(
        select(func.sum(Block.audio_duration_ms))
        .join(Document)
        .where(Document.user_id == user.id)
    )

    # Document count
    doc_count = await db.exec(
        select(func.count(Document.id))
        .where(Document.user_id == user.id)
    )

    # By model... etc

    return {
        "total_audio_ms": total_ms.one_or_none() or 0,
        "document_count": doc_count.one(),
        "by_model": {...},
    }
```

## Account Deletion

### What Happens

| Data | Action |
|------|--------|
| Documents | Hard delete (cascades to Blocks → BlockVariants) |
| Filters | Hard delete |
| UserSubscription | Cancel Stripe sub first, then anonymize |
| UsagePeriod | Anonymize |
| UsageLog | Anonymize |
| metrics_event (SQLite) | Anonymize |
| Stack Auth | Delete via API |
| Audio cache | Orphaned, expires naturally |

### Anonymization

`user_id = "deleted-{hash_of_original_user_id}"`

Preserves usage patterns for aggregate analysis while being fully anonymous (no PII in those tables).

### Endpoint

`DELETE /v1/users/me`

```python
@router.delete("/users/me")
async def delete_account(
    password: str = Body(..., embed=True),  # Require password confirmation
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    # 1. Verify password via Stack Auth
    # (need to research Stack Auth API for password verification)

    # 2. Cancel Stripe subscription if active
    sub = await db.get(UserSubscription, user.id)
    if sub and sub.stripe_subscription_id and sub.status in ("active", "trialing"):
        stripe.Subscription.cancel(sub.stripe_subscription_id)

    # 3. Delete user-owned data
    await db.exec(delete(Filter).where(Filter.user_id == user.id))
    await db.exec(delete(Document).where(Document.user_id == user.id))  # Cascades

    # 4. Anonymize billing data
    anon_id = f"deleted-{hashlib.sha256(user.id.encode()).hexdigest()[:12]}"
    await db.exec(
        update(UserSubscription).where(UserSubscription.user_id == user.id)
        .values(user_id=anon_id)
    )
    await db.exec(
        update(UsagePeriod).where(UsagePeriod.user_id == user.id)
        .values(user_id=anon_id)
    )
    await db.exec(
        update(UsageLog).where(UsageLog.user_id == user.id)
        .values(user_id=anon_id)
    )

    # 5. Anonymize metrics (SQLite)
    # await metrics_db.execute(
    #     "UPDATE metrics_event SET user_id = ? WHERE user_id = ?",
    #     (anon_id, user.id)
    # )

    # 6. Delete from Stack Auth
    await stack_auth_client.delete_user(user.id)

    await db.commit()
    return {"deleted": True}
```

### UX

- Password confirmation modal
- Immediate deletion (no grace period)
- Clear warning: "This action is irreversible"

## Email/Password Change

**NEEDS RESEARCH:** How does Stack Auth handle this?

Questions to answer:
1. Does Stack Auth have a hosted account settings page we can link to?
2. If user changes email there, how do we get notified? Webhook?
3. Is it cleaner to use their API from our own UI?
4. How to verify current password for deletion confirmation?

Check Stack Auth docs: https://docs.stack-auth.com/

## Frontend

### Settings Page Route

`/settings` or `/account`

Components:
- Stats card (total audio, docs, LOTR comparison)
- Model breakdown chart/list
- Delete account button → confirmation modal with password input
- Email/password section (depends on Stack Auth research)

## Sources

- `yapit/gateway/domain_models.py` — all models with user_id
- `yapit/gateway/api/v1/billing.py` — Stripe subscription handling
- Stack Auth docs for user deletion API

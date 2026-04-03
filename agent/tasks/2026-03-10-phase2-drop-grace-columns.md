# Phase 2: Drop Legacy Grace Period Columns

status: done

## What

Drop `grace_tier`, `grace_until`, `previous_plan_id` from `UserSubscription`. Code no longer reads/writes these (since 97ef75c).

## Precondition

```sql
SELECT count(*) FROM usersubscription WHERE grace_until > NOW();
```

Must return 0. As of 2026-03-10, 1 row remains (expires ~Mar 22).

## Steps

1. Remove the three fields from `UserSubscription` in `domain_models.py`
2. `make migration-new MSG="drop legacy grace columns"`
3. Review generated migration — should be three `drop_column` ops
4. Deploy

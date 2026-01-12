# Migrations

Alembic database migrations for Yapit.

## Shared Database

**Yapit and Stack Auth share the same Postgres database.**

- Stack Auth tables: PascalCase (`Project`, `ProjectUser`, `Team`)
- Yapit tables: snake_case (`ttsmodel`, `usersubscription`, `document`)
- Stack Auth also creates `_prisma_migrations` table and enum types

**Never drop all tables blindly.** The `env.py` filters to only include `MANAGED_TABLES` (tables from our SQLModel models), so alembic ignores Stack Auth. But raw SQL or `DROP SCHEMA` would destroy everything.

## Creating a Migration

```bash
make migration-new MSG="description"
```

**Prerequisites:** Models in `domain_models.py` updated, code imports work.

**What it does:**
1. Starts postgres if needed
2. Drops yapit DB, runs existing migrations (recreates pre-change state)
3. Autogenerates migration from model diff
4. Auto-fixes SQLModel quirks (`AutoString()` → `String()`)
5. Tests on fresh DB (`yapit_test`)

**Always review the generated migration:**

| Issue | Why | Fix |
|-------|-----|-----|
| Renames show as drop + create | Autogenerate can't detect renames | Manual `op.rename_table()` or `op.alter_column()` |
| Table drops not generated | Deleted model = not in `MANAGED_TABLES` = ignored | Manual `op.drop_table()` |
| Data migrations missing | Autogenerate only handles schema | Add manual data migration code |
| Enum changes broken | Postgres enum handling is tricky | Manual enum ops |
| Column constraint fails on prod | Existing data may violate new constraint | Check prod data first: `SELECT ... WHERE length(col) > N` |

After generating: `make dev-cpu` to restart and apply.

## Deploying

**No special action.** Gateway runs `alembic upgrade head` on startup.

## How MANAGED_TABLES Works

`yapit/gateway/migrations/env.py`:

```python
MANAGED_TABLES = {table.name for table in target_metadata.sorted_tables}

def include_object(object, name, type_, reflected, compare_to):
    if type_ == "table":
        return name in MANAGED_TABLES
    ...
```

Only tables from our SQLModel models are included. Stack Auth tables are invisible to alembic.

**Gotcha:** When you delete a model, the table disappears from `MANAGED_TABLES`, so alembic won't generate a drop. You must write it manually.

## Key Files

| File | Purpose |
|------|---------|
| `yapit/gateway/migrations/env.py` | Alembic config, MANAGED_TABLES filter |
| `yapit/gateway/migrations/versions/` | Migration files |
| `yapit/gateway/domain_models.py` | SQLModel definitions |
| `Makefile` | `make migration-new` command |

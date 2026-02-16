---
status: active
started: 2026-02-02
---

# Task: Migrate Postgres to Hetzner Volume

## Intent

When VPS disk (~350GB, or ~650GB if upgraded to medium perf tier) fills up with user document data, move Postgres data directory to a Hetzner Volume (up to 1TB, €0.0528/GB/month incl. VAT).

Not urgent now — this is a reference for when we approach disk limits.

## Napkin Math

Storage per user type (generous overhead estimates):
- Paying user: ~800MB → €0.042/month on volume
- Free signed-in: ~80MB → €0.004/month
- Guest: ~15MB → €0.0008/month (regular cleanup of unused)

Break-even points (Postgres only, assuming caches stay on VPS disk):
- 350GB disk: ~437 paying users before full
- 650GB disk: ~812 paying users (minus cache space)

Volume costs at scale:
- 100 paying users: ~€4.22/month
- 500 paying users: ~€21/month
- 1000 paying users: ~€42/month

## Approach

Standard block storage migration:
1. Create volume, mount (e.g. `/mnt/pgdata`)
2. Stop Postgres
3. `rsync` data directory to volume
4. Update `data_directory` in `postgresql.conf`
5. Start Postgres
6. No application code changes needed

Volumes are resizable (grow only) without downtime.

## Sources

- Reference: [[vps-setup]] — current prod server config
- Reference: `scripts/margin_calculator.py` — update with volume costs when implementing

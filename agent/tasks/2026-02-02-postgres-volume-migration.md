---
status: active
started: 2026-02-02
---

# Task: Migrate Postgres to Hetzner Volume

## Intent

When VPS disk (~350GB, or ~650GB if upgraded to medium perf tier) fills up with user document data, move Postgres data directory to a Hetzner Volume (up to 1TB, €0.0528/GB/month incl. VAT).

Not urgent now — this is a reference for when we approach disk limits.

## Napkin Math

Storage per user type — **corrected Feb 2026** with TOAST compression data:
- `STORAGE_ACTUAL_MULTIPLIER` was 1.6 (estimated), actual measured ~0.5x (TOAST compresses structured_content ~4.8x)
- Paying user: ~250MB actual on-disk (500MB limit × 0.5x TOAST, 100% utilization)
- Free signed-in: ~25MB
- Guest: ~5MB

Break-even points (350 GB available for Postgres, conservative):
- All-paid worst case: **~1,430 users**
- Realistic mix (30/50/20 guest/free/paid): **~5,600 users**

If Block table eliminated: capacity roughly doubles. See [[2026-02-16-structured-content-compute-vs-store]] research.

## Approach

Standard block storage migration:
1. Create volume, mount (e.g. `/mnt/pgdata`)
2. Stop Postgres
3. `rsync` data directory to volume
4. Update `data_directory` in `postgresql.conf`
5. Start Postgres
6. No application code changes needed

Volumes are resizable (grow only) without downtime.

## Revised Estimates (Feb 2026)

**Actual prod data (353 docs):** Total DB = 20 MB. Breakdown: blocks 46.6%, structured_content 33.4%, original_text 19.5%.

TOAST compresses structured_content ~4x — the "6-8x raw JSON bloat" doesn't apply to on-disk storage. Actual structured_content/original_text ratio is **~1.6x** for real documents (not 6-8x).

This means per-user storage estimates from the original napkin math are significantly overstated. The earlier ~800MB/paid-user estimate should be revisited with actual per-user data once there are real paying users.

Hetzner volume pricing: €0.044/GB/month (Feb 2026).

## Future: Structured Content on R2 (Direct Fetch)

Once user base is geographically distributed (significant US/Asia traffic), consider moving `structured_content` blobs from Postgres to R2 with **frontend direct fetch** (same pattern as images). Browser fetches JSON from nearest Cloudflare edge instead of round-tripping to Germany.

This improves latency for distant users and reduces Postgres storage, but adds architectural complexity (two-request document load, R2 dependency on critical path). Not worth it while users are mostly European or before thousands of paying users.

Research: `agent/research/2026-02-16-structured-content-compute-vs-store.md`

## Sources

- Reference: [[vps-setup]] — current prod server config
- Reference: `scripts/margin_calculator.py` — update with volume costs when implementing

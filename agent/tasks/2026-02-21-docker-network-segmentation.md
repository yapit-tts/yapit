---
status: backlog
refs:
  - "[[2026-02-21-red-team-security-audit]]"
  - "[[security]]"
  - "[[infrastructure]]"
---

# Docker network segmentation

## Intent

All prod services share one `yapit-network`. Textbook defense-in-depth recommendation, but marginal value for this setup.

## Why it's low priority

- **Gateway** is both the most likely compromise target AND legitimately needs access to everything (Postgres, Redis, Stack Auth, Smokescreen, Markxiv). Segmentation doesn't help here.
- **Workers** are the only services that could benefit from isolation (they only need Redis). But worker compromise is unlikely — they pull pinned models at build time, run offline (`HF_HUB_OFFLINE=1`), and process text/images from the job queue, not arbitrary user input.
- **Frontend** (nginx) segmentation adds nothing — if nginx is compromised, reaching the gateway is equivalent to what any internet user can do. The gateway is the trust boundary.
- Adds compose complexity (multi-network configs are harder to debug).

## If we do it

Separate `worker-net` (workers + Redis) so workers can't reach Postgres/Stack Auth. Skip frontend segmentation — not worth the complexity.

## Done When

- Workers on a separate network with access to Redis only
- Everything else unchanged

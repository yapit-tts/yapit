---
status: done
started: 2026-01-03
completed: 2026-01-06
---

# Task: Hetzner Backups + Restore Drill

**Knowledge extracted:** [[backup-rollback]]

## Summary

Researched and documented backup/rollback procedures. Key findings:
- Hetzner backups enabled (~€1.10/mo), daily automatic, 7-day rolling
- Live snapshots are safe for Postgres (WAL handles consistency)
- Code rollback is trivial (docker service rollback or specific commit redeploy)
- DB issues: forward-fix preferred; restore from backup if catastrophic

## Remaining

- [ ] Actually run restore drill on test VPS (deferred — low priority for soft launch)

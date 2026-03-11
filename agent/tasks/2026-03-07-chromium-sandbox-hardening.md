---
status: done
refs: [4a8bf79]
---

# Chromium isolation via dedicated container

Original task explored enabling Chromium's sandbox inside the gateway. Research found that was fragile (daemon-level seccomp/AppArmor overrides, Swarm can't apply custom seccomp profiles per-service). Instead, moved Playwright into a dedicated `defuddle` container with network segmentation — stronger isolation, no SYS_ADMIN needed. See commit ref once merged.

## Research

- [[2026-03-07-chromium-sandbox-hardening]] — Three layers block the sandbox, Swarm constraints, approach comparison. Conclusions superseded by container isolation approach.

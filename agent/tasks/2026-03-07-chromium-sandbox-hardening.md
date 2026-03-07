---
status: backlog
refs: []
---

# Enable Chromium sandbox in gateway container

## Intent

Playwright runs Chromium inside the gateway container with `cap_drop: [ALL]`. This prevents Chromium from creating user namespaces for its sandbox, so it silently falls back to `--no-sandbox`. The renderer process that executes arbitrary page JavaScript runs unsandboxed — a single renderer exploit gives access to the gateway process (Postgres creds, Redis, API keys, user data).

Website extraction is unauthenticated — anyone can submit a URL. The attacker controls which page Chromium navigates to.

## Assumptions

- Chromium's sandbox (seccomp-bpf + user namespaces) is a meaningful defense layer worth enabling. Without it, Docker container isolation is the only boundary.
- `kernel.unprivileged_userns_clone=1` on the host is the cleanest fix — lets Chromium sandbox work without granting `SYS_ADMIN` to the container. Most modern kernels default to this but some distros disable it.
- Alternative: `SYS_ADMIN` capability on the gateway container. Undesirable — it's an overly broad capability just to enable namespace creation.
- Moving Playwright to a separate container is the nuclear option. Maximum isolation but re-introduces sidecar complexity we just removed.

## Done when

- Chromium sandbox confirmed running (not falling back to `--no-sandbox`)
- No new broad capabilities added to the gateway container
- Security knowledge file updated

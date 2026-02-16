---
status: active
started: 2026-02-08
---

# Task: Restrict SSH to Tailscale, switch to manual deploys

## Intent

Close port 22 on the public internet (Hetzner firewall + UFW) so SSH is only reachable via Tailscale. This eliminates exposure to SSH zero-days (e.g., regreSSHion CVE-2024-6387) and brute force entirely.

The blocker is CI/CD: current workflow auto-deploys on merge to main via GitHub Actions SSH. Options considered:

1. **Tailscale GitHub Action** — joins an ephemeral node to the tailnet per CI run. Works, but adds fragility (Tailscale coordination server dependency, OAuth secret management, ACL maintenance). Feels like trading one risk for another.

2. **Manual deploys via `make deploy`** — remove auto-deploy from CI. Deploy becomes a local `make` target that SSHes via Tailscale. Simpler, no CI dependency on Tailscale. Downside: manual step after every merge.

## Decision

**Defer until the app stabilizes.** Right now, frequent pushes make manual deploys annoying. Once update cadence slows down, switch to:
- Manual `make deploy` from local machine (via Tailscale SSH)
- Close port 22 publicly
- CI only runs tests, no deploy step

## When to revisit

When deploy frequency drops to ~weekly or less. At that point the manual step is negligible and the security benefit is clear.

## Assumptions

- Tailscale stays reliable (it has been so far)
- Hetzner web console is the emergency fallback if Tailscale goes down
- Key expiry is disabled on the VPS Tailscale node (done 2026-02-08)

## Considered & Rejected

- **Tailscale GitHub Action for CI deploys**: Too brittle for the security gain. Adds a dependency on Tailscale's infra being up during every CI run, OAuth secret rotation, ACL rules. A compromised runner with scoped ACLs has equivalent access to today's SSH key, so net security improvement is marginal while operational complexity increases.
- **Restricting port 22 to GitHub Actions IP ranges**: GitHub's ranges change, requiring ongoing maintenance. Not worth it.

## Sources

**Knowledge files:**
- [[vps-setup]] — current SSH/firewall config

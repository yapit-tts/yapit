---
status: done
started: 2025-01-09
---

# Task: Monitoring Evolution Brainstorm

Related: [[logging-observability]] — current implementation (SQLite + loguru)

## Intent

Evaluate whether to evolve our monitoring/logging setup beyond the current SQLite + loguru approach. Three directions to consider:

1. **Sentry** — Error tracking, maybe frontend too. Replace ad-hoc error handling?
2. **Prometheus/Grafana** — Full observability stack. Overkill or worth it?
3. **Claude-in-the-loop** — Keep current setup, add smart script/plugin that:
   - Watches logs for errors/warnings we haven't explicitly ignored
   - Spins up Claude to investigate whether it's a real issue
   - Creates alerts (Discord webhook?) with diagnosis
   - Maybe even auto-creates PR with fix
   - Cheap: only activates on trigger

## Questions to Explore

- Is our current SQLite + loguru sufficient for prod?
- What gaps exist? (alerting, frontend errors, distributed tracing?)
- Sentry free tier limits? Worth the complexity?
- Prometheus: do we even need metrics beyond what we have?
- Claude-in-the-loop: any existing tools/patterns for this?

## Sources

- [[logging-observability]] — MUST READ, current architecture and decisions

## Notes

**Direction: Claude-in-the-loop (option 3)**

Simple approach:
- systemd timer → `claude -p` with clear instructions
- Check logs for errors/warnings → notify via ntfy → investigate → write `yyyy-mm-dd-incident-xyz.md`
- Either: Claude with SSH read-only into prod logs, OR instance running on VPS with fine-grained read-only perms (preferred)
- Sonnet via `claude -p` with explicit instructions (not OpenRouter free models — clarity > cost savings here)

Sophisticated tools for this probably exist, but this should... just work?

**Beyond error detection — periodic health analysis:**

Give Claude permission to run pre-curated scripts (not manual analysis every time):
- Queue depth trends — has it been filling up too much lately?
- Runpod overflow usage — hitting serverless too often? demand surge?
- Usage spikes — unusual patterns?
- System metrics — CPU utilization, disk utilization
- API call volumes (esp checkingn things like RPM for Gemini or Inworld where we have limits)

Time series analysis: "is this normal or concerning?"

**Out of scope:** Cost monitoring — better done manually or with existing billing integrations.

**Scope definition:** Error logs + performance + system stability + scaling. Not billing/costs.

**Why not Sentry/Prometheus:**
- Already rejected as "GUI-based, not LLM-friendly, overkill" in [[logging-observability]]
- Current SQLite + loguru fits the "LLM agents query directly" philosophy
- Claude-in-the-loop is the natural extension: automate the trigger instead of manual checks

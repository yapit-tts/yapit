# Overview

Yapit is an open-source TTS platform for reading documents and web pages.

## Core

- [[tts-flow]] — Audio synthesis pipeline: WebSocket protocol, Redis queues, pull-based workers, caching. Read for TTS bugs, latency issues, worker scaling.
- [[document-processing]] — How content becomes blocks: input paths (text/URL/file), Gemini extraction, YOLO figure detection, markdown parsing, block splitting. Read for document upload bugs, extraction failures, rendering issues.
- [[frontend]] — React architecture, component hierarchy, chrome devtools MCP workflows. Read for UI work, frontend debugging.
- [[features]] — User-facing capabilities: sharing, JS rendering, etc.

## Operations

- [[migrations]] — Alembic workflow, MANAGED_TABLES filter, seed data. Read before any DB schema changes.
- [[vps-setup]] — Production server config, Traefik, debugging. Read for prod issues.
- [[infrastructure]] — Docker compose structure (base/dev/prod layers), CI/CD pipeline, worker services, config change checklist. Read for deployment issues or adding services.
- [[env-config]] — Secrets management, .env files, sops encryption.
- [[dev-setup]] — **READ BEFORE TESTING.** Test commands, fixture gotchas, uv/pyproject structure. Tests WILL fail without proper env setup.
- [[dependency-updates]] — Version-specific gotchas, license checking. Read before updating/adding dependencies.
- [[metrics]] — TimescaleDB pipeline, event types, dashboard, health reports. Read when adding/modifying metrics.
- [[logging]] — Loguru JSON logging configuration.

**Testing:** You can claim "all tests pass" if and only if `make test-local` passes (after `make dev-cpu` if you made backend changes).

## Auth

- [[auth]] — Stack Auth integration, token handling.

## Billing

- [[stripe-integration]] — Token-based billing, waterfall consumption, Stripe SDK gotchas, webhook handling. Read for billing bugs, subscription issues.

## Security

- [[security]] — Security considerations and audits.

## Legal

- [[licensing]] — Dependency license checking.

## Notes for distill agents

- Upon any metrics/logging changes, update the monitoring agent prompt in `scripts/report.sh`.


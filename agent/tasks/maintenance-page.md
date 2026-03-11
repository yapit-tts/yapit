---
status: done
---

# Maintenance page for downtime

Add a static maintenance page served by nginx when the backend is unreachable. Users see a friendly message instead of raw 502/503 errors.

## Approach

`error_page 502 503 /maintenance.html` in `frontend/nginx.conf`, with a static HTML file in `frontend/public/`. Should match the app's visual style (dark bg, logo, brief message like "Back shortly").

## Research

- [[2026-03-01-maintenance-page]]

## Sources

- `frontend/nginx.conf`
- `frontend/public/`

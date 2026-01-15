---
status: done
started: 2026-01-03
completed: 2026-01-05
---

# Task: OAuth Providers Setup

Add GitHub and Google login options.

- Create OAuth apps in GitHub and Google developer consoles
- Configure in Stack Auth dashboard
- Test login flow

## Gotchas

**Self-hosted Stack Auth needs its own redirect URI:** When migrating to self-hosted Stack Auth, you must add the new callback URL to each OAuth provider (Google Cloud Console, GitHub, etc.). The redirect URI changes from `https://api.stack-auth.com/...` to `https://your-auth-domain/api/v1/auth/oauth/callback/{provider}`.

# Guest Users

Anonymous/guest sessions use `anon-{uuid}` as `user_id`. HMAC-signed, no Stack Auth persistence.

## Cleanup

Background task (`_guest_cleanup_task` in `gateway/__init__.py`) runs daily. Deletes guest users inactive for 30 days (`GUEST_DOC_TTL_DAYS`) — all their documents, images, and preferences. Also sweeps orphaned guest preferences with no documents. ToS covers this: "Anonymous (guest) sessions and their data are temporary and may be deleted at any time" (`TermsPage.tsx`).

Returning guests get a working session (HMAC is stateless) but an empty library.

## Monitoring

- `scripts/guest_users.py` — storage, activity, idle days per guest user. `--inactive N` for TTL candidates.
- Dashboard User Type filter (sidebar) — segments raw metrics events (30-day window, not daily aggregates)

## Risk Notes

No per-IP rate limit on session creation. No global concurrent extraction cap across all users. Guest extractions are cheap (defuddle/PyMuPDF, no external APIs) but can saturate VPS CPU during traffic spikes.

## Related

- [[auth]] — anonymous flow, claim-anonymous
- [[rate-limiting]] — per-user caps

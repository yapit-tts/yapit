---
status: done
type: implementation
completed: 2026-01-01
---

# Task: Subscription Frontend

## Goal

Replace the credits-based UI with subscription-based billing. Users should be able to:
- See their current plan and usage
- Subscribe to a plan (checkout via Stripe)
- Manage their subscription (via Stripe billing portal)

Reference: [[subscription-backend-refactor]] for backend implementation, [[pricing-strategy-rethink]] for tier structure.

## Relevant Files

- `frontend/src/pages/SubscriptionPage.tsx` — main subscription page
- `frontend/src/components/documentSidebar.tsx` — sidebar with plan button + usage bar
- `frontend/src/pages/CheckoutSuccessPage.tsx` — post-checkout confirmation
- `frontend/src/pages/CheckoutCancelPage.tsx` — checkout cancellation
- `frontend/src/layouts/MainLayout.tsx` — return URL redirect after sign-in
- `yapit/gateway/api/v1/billing.py` — backend endpoints

## Implementation Complete

- [x] Created `SubscriptionPage.tsx` with plan cards, usage bars, monthly/yearly toggle
- [x] Updated sidebar footer — subscription button with plan name + usage progress bar
- [x] Updated `CheckoutSuccessPage.tsx` — polls `/v1/users/me/subscription`
- [x] Updated `CheckoutCancelPage.tsx` — redirects to /subscription
- [x] Route changed from `/credits` to `/subscription`
- [x] Deleted old `CreditsPage.tsx`
- [x] Fixed portal return URL (`/settings` → `/subscription`)
- [x] Fixed scrollbar issue on subscription page
- [x] Removed "Popular" badge from Plus plan
- [x] Fixed units display — hours shown as approximate (~X hrs), 0 usage shows "0 hrs" not "Not included"
- [x] Added tooltips to usage bars (exact character counts)
- [x] Added tooltip to sidebar plan button (shows usage + OCR limit)
- [x] Sign-in redirect — uses localStorage to return to /subscription after auth

## Gotchas

### Characters vs Hours
Backend tracks `premium_voice_characters`. The conversion to hours is approximate:
- ~17 characters = 1 second of audio
- ~61,200 characters = 1 hour
- Plan limits in DB are stored as characters (e.g., Plus = 1,224,000 chars ≈ 20 hrs)

UI shows hours with `~` prefix to indicate approximation. Tooltips show exact character counts.

### Sign-in Return URL
Stack Auth doesn't support dynamic `afterSignIn` URLs via query params. Solution: localStorage.
- `SubscriptionPage` sets `localStorage.setItem("returnAfterSignIn", "/subscription")` before redirect
- `MainLayout` checks for this on user login and redirects if present

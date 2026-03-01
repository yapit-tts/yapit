---
status: backlog
refs:
  - "[[2026-02-21-red-team-security-audit]]"
  - "[[2026-02-09-content-security-policy]]"
  - "[[security]]"
---

# Deploy Content Security Policy

## Intent

Defense-in-depth against XSS. Primary defenses are already strong (zero `dangerouslySetInnerHTML`, typed AST renderer, no inline scripts, no dynamic script loading). CSP would limit blast radius if a dependency zero-day (KaTeX, Stack Auth SDK) or future regression slips through.

## Priority Assessment

Deprioritized. XSS impact is client-side only — attacker gets one user's session. No PII beyond email, no payment details client-side. Main risk is exfiltrating a user's documents (ToS discourages sensitive uploads, but people ignore that). The realistic XSS vector is a dependency zero-day, which gets patched quickly and is unlikely to be weaponized against a small app before patching. Revisit if handling more sensitive data or going through a formal security audit.

## Approach

Add `Content-Security-Policy` header in `frontend/nginx.conf`. Deploy with `Content-Security-Policy-Report-Only` first, use the app for a few days, fix violations, then flip to enforcing.

Full policy (validated against codebase 2026-02-28):

```
default-src 'self';
script-src 'self' 'wasm-unsafe-eval' 'sha256-<hash-of-index.html-dark-mode-script>';
style-src 'self' 'unsafe-inline';
img-src 'self' https: data:;
media-src 'self' blob: data:;
connect-src 'self' wss://yapit.md https://auth.yapit.md https://huggingface.co https://cdn-lfs.huggingface.co;
font-src 'self';
worker-src 'self';
frame-src 'none';
object-src 'none';
base-uri 'self';
form-action 'self';
```

Key justifications:
- `wasm-unsafe-eval` — ONNX runtime for browser TTS (Kokoro.js)
- `sha256-<hash>` — inline dark mode script in `index.html:29-43` (must regenerate if script changes)
- `style-src 'unsafe-inline'` — KaTeX generates inline `style` attributes in DOM, unavoidable without patching KaTeX
- `media-src blob: data:` — audio playback via `URL.createObjectURL`, silent WAV mobile unlock (`data:audio/wav;base64,...`)
- `connect-src` HuggingFace domains — browser TTS downloads ONNX models at runtime
- `form-action 'self'` — Stripe checkout uses `window.location.href` redirect, not form submission

## Pre-implementation cleanup

- Move inline `<style>` from `AccountSettingsPage.tsx:17` to CSS file
- Move inline `<style>` from `batchLoadingAnimations.tsx:125` to CSS file
- (Both are nice-to-do regardless, but `style-src 'unsafe-inline'` is needed for KaTeX anyway)

## Corrections from earlier assumptions

- Stack Auth does NOT use iframes for token refresh. It uses cookie-based token storage with HTTP fetch to `https://auth.yapit.md/api/v1/auth/oauth/token`. No `frame-src` entry needed.
- Stripe is not loaded client-side. No `@stripe/stripe-js`. Checkout is a server-side redirect.

## Done When

- CSP header deployed in nginx.conf (all location blocks with existing `add_header`)
- Report-only mode validated with no violations in normal usage
- Switched to enforcing mode

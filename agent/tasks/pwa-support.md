---
status: done
started: 2025-01-05
completed: 2025-01-05
---

# Task: PWA Support (Installable Web App)

## Intent

Add PWA manifest so users can "install" Yapit as a standalone app on desktop/mobile. When installed:
- App appears in home screen/app drawer/start menu
- Opens in own window without browser chrome (address bar, tabs)
- Feels like a native app

**Scope:** Minimal — manifest + icons + meta tags. No service worker/offline support (TTS streams from backend anyway).

## What's Needed

1. **`manifest.json`** in `frontend/public/`:
   - `name`: "Yapit" (or "Yapit TTS"?)
   - `short_name`: "Yapit"
   - `start_url`: "/" (or "/library"?)
   - `display`: "standalone"
   - `theme_color`: from current Ghibli theme (green primary)
   - `background_color`: cream/warm white from theme
   - `icons`: array of PNG icons at various sizes

2. **Link in HTML** — `<link rel="manifest" href="/manifest.json">`

3. **iOS meta tags** (Safari doesn't fully support manifest):
   - `<meta name="apple-mobile-web-app-capable" content="yes">`
   - `<meta name="apple-mobile-web-app-status-bar-style" content="default">`
   - `<link rel="apple-touch-icon" href="/icons/icon-192.png">`

4. **PNG icons** — Generate from `favicon.svg`:
   - 192x192 (minimum for Chrome)
   - 512x512 (minimum for Chrome)
   - Optionally more sizes for iOS (180x180) and different contexts

## Decisions

- **Approach:** Manual (no vite-plugin-pwa). Simpler, no new deps. Can add plugin later if offline replay becomes a goal.
- **Start URL:** `/` (homepage). Natural entry point for all users.
- **Icons:** Minimal — 192x192 + 512x512 only. Good enough for v1.
- **Theme colors:** `#f5f0e6` (warm cream background), `#4a8a4d` (green primary) — from oklch values in index.css

## Sources

- favicon.svg exists at `frontend/public/favicon.svg` — branded tree-Y with sound waves
- Web App Manifest spec: https://developer.mozilla.org/en-US/docs/Web/Manifest

## How Users Install

**Desktop (Chrome/Edge):**
- Visit the site → icon appears in address bar (right side) → click "Install"
- Or: three-dot menu → "Install Yapit..." / "Add to Desktop"
- App appears in Start Menu / Applications folder

**Mobile (Android Chrome):**
- Visit the site → banner may appear: "Add Yapit to Home screen"
- Or: three-dot menu → "Add to Home screen" / "Install app"
- App appears in app drawer like a native app

**Mobile (iOS Safari):**
- Share button → "Add to Home Screen"
- (iOS doesn't auto-prompt, user must know the gesture)

**What triggers the install prompt:**
Chrome shows the install option when it detects a valid manifest with required fields (name, icons, start_url, display: standalone). No service worker required for the basic prompt.

## Implementation Steps

1. Generate PNGs from favicon.svg:
   ```bash
   cd frontend/public
   inkscape -w 192 -h 192 favicon.svg -o icon-192.png
   inkscape -w 512 -h 512 favicon.svg -o icon-512.png
   ```

2. Create `frontend/public/manifest.json`:
   ```json
   {
     "name": "Yapit",
     "short_name": "Yapit",
     "start_url": "/",
     "display": "standalone",
     "background_color": "#f5f0e6",
     "theme_color": "#4a8a4d",
     "icons": [
       { "src": "/icon-192.png", "sizes": "192x192", "type": "image/png" },
       { "src": "/icon-512.png", "sizes": "512x512", "type": "image/png" }
     ]
   }
   ```

3. Add to `frontend/index.html` `<head>`:
   ```html
   <link rel="manifest" href="/manifest.json">
   <meta name="theme-color" content="#4a8a4d">
   <!-- iOS -->
   <meta name="apple-mobile-web-app-capable" content="yes">
   <link rel="apple-touch-icon" href="/icon-192.png">
   ```

Vite serves `public/` at root, so paths like `/manifest.json` and `/icon-192.png` work automatically.

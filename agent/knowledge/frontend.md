
## Chrome DevTools MCP

Use Chrome DevTools MCP to visually verify changes, test user flows, and debug issues.

**Dev account:** `dev@example.com` / `dev-password-123` (from `scripts/create_user.py`)
- MCP browser has separate session - login required on first use
- Login: navigate to localhost:5173 → click Login → fill form → Sign In

**Key commands:**
- `take_screenshot` — see rendered UI
- `take_snapshot` — get DOM tree with element UIDs
- `click`, `fill`, `fill_form` — interact using UIDs from snapshot
- `list_console_messages` — check for JS errors/warnings
- `resize_page` — test responsive (375x812 for mobile, 1280x800 for desktop)

**Use for:**
- Visual verification after UI changes
- Console error checking (React errors, failed requests)
- Mobile/responsive layout testing
- User flow testing (login → input → playback → controls)
- Edge case verification without manual testing

**⚠️ CONTEXT WARNING — Large Snapshots:**
Action tools (click, fill, hover, etc.) automatically return full page snapshots. On complex documents this can be **30k+ tokens per interaction** — enough to consume most remaining context in one call.

**Before any DevTools interaction:**
1. **Create your own small test document** — don't use pre-existing documents in the sidebar, they're often huge (real webpages, long docs). Type a few lines of test content yourself.
2. **Sync task file first if context < 50%** — write current findings and next steps before the snapshot might consume remaining context
3. **Prefer screenshots for visual checks** — `take_screenshot` is much smaller than snapshots

**Exceptions:**
- If debugging a specific bug on a known large document, the large snapshot is unavoidable — just be handoff-ready first.
- For many bugs, screenshots lack precision — DevTools snapshots let you inspect element UIDs, exact positioning, and DOM structure. When you need that accuracy, the snapshot cost is worth it.

**If MCP won't connect:** Ask the user to close Chrome so MCP can launch a fresh instance.

**CSS debugging pattern:** When a style isn't applying, don't keep trying fixes at the same DOM level. Immediately trace upward:
```
element (Xpx) → parent (Ypx) → grandparent (Zpx) → ...
```
Find which ancestor is the constraint, fix there. Flex containers especially: children don't auto-stretch width in flex-row parents without `w-full`.


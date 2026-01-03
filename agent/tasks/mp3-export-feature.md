---
status: active
started: 2026-01-03
---

# Task: MP3 Export / Full Document Audio Download

Export entire document as single audio file for offline listening.

## Features

- **Voice selection** — pick which voice to use for conversion
- **No speed toggle** — leave at 1x, user can adjust in their audio player
- **Character count preview** — "This document has X characters, will use Y of your quota"
- **Chapter/section selection** — for documents with headers:
  - Show list of detected sections (from structured markdown)
  - Checkboxes to include/exclude sections
  - Use cases: drop reference section, convert only chapters 2-5, etc.

## UI

Disabled placeholder button already exists ("Export as audio - coming soon"). Need to implement the actual export dialog/flow.

## Notes

This is batch synthesis — will take time for long documents. Need progress indicator.
should also make sure not to you know spam requests but send them in a reasonable frequency i mean it's probably overkill to check to like monitor the queue length and like whether there's high system load and i'm not sure i mean actually probably it's not it's not that hard actually  because yeah it's a back-end implementation right so we'd probably have a route for batch synthesis and then we can just ask query the redis queue and depending on the load like if it's very empty the workers aren't that busy then we can send a few more requests and otherwise we deprioritize the batch requests a little bit to have the real time take priority  I mean it's a different case for of course for example for the inworld TTS API but I think yeah I mean where we also you know there basically they can take infinite requests in theory but I mean there we also have rate limits but those I think we can easily increase yeah actually I think in the docs they say they can be increased at no additional charge so if we run into rate limits there.  yeah i can just increase them

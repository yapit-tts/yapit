---
status: active
started: 2026-01-03
---

# Task: Worker Timeout/Retry Handling

Edge case: block sent to server worker which fails to process (worker crash / OOM / whatever).

- Is there a timeout after which we retry?
- Or do we just hang forever?

Need to verify this is handled properly.

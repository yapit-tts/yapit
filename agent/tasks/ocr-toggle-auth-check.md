---
status: active
started: 2026-01-03
---

# Task: OCR Toggle Auth/Plan Check

OCR toggle appears usable on free plan — should be disabled.

Check that:
- Frontend disables/hides OCR toggle for free users
- Backend rejects OCR requests from free users (defense in depth)
- Proper error message if somehow triggered without plan

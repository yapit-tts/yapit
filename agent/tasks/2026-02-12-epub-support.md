---
status: active
started: 2026-02-12
---

# Task: Add epub and image upload support

Two new content types for document uploads:

1. **Images** (png, jpeg, webp, heic, heif) — Gemini API supports these but they're not wired up as a document input path currently.
2. **Epub** — Gemini doesn't accept epub natively; epubs are zipped XHTML with embedded images. Extraction approach TBD.

## Sources

- [[document-processing]] — current input paths and processor architecture

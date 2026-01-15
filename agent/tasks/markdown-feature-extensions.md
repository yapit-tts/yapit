---
status: backlog
---

# Markdown Feature Extensions

Capture markdown features to add as real needs arise from documents/webpages/user feedback.

## Footnotes

**Status:** Not started

**Syntax:** `text[^1]` ... `[^1]: footnote content`

**Behavior:**
- Render inline reference as superscript link
- Collect footnote definitions at bottom (or hover?)
- TTS: Only read when navigating to the footnote block itself, not inline

**Implementation sketch:**
- Enable `mdit-py-plugins.footnote`
- Add `FootnoteRefInline` and `FootnoteBlock` to models
- Transformer handles `footnote_ref` and `footnote_block` node types

---

*Add more features here as genuine annoyances surface.*

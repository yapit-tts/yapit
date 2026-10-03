# Pandoc EPUB Cross-File Footnotes Bug

## Issue

Pandoc drops footnotes when the note reference (`doc-noteref`) and note definition (`doc-endnotes`) are in different XHTML files within the EPUB — which is the standard EPUB3 pattern.

## Root Cause

`src/Text/Pandoc/Readers/EPUB.hs` parses each spine XHTML file via separate `readHtml` calls (line 90). The HTML reader's `noteTable` state is local to each call. References in `ch01.xhtml` create `rawInline "noteref"` elements, but `noteTable` is empty because the definitions are in `notes.xhtml`. When `notes.xhtml` is parsed separately, it populates `noteTable` in a different `readHtml` invocation. The final `replaceNotes'` pass (line 126-127) can't match refs to defs across calls.

The fix would be ~5 lines: aggregate `noteTable` across spine items in `archiveToEPUB`, then run `replaceNotes'` on the combined AST.

## Existing Issues

- [#5531](https://github.com/jgm/pandoc/issues/5531) — "epub noterefs across files not properly converted" (2019, open). jgm confirmed: "pandoc currently will only pick up footnotes that are defined in the same file."
- [#7884](https://github.com/jgm/pandoc/issues/7884) — "Converting Epub with noteref drops `<a>` in result" (2022, closed with partial fix — adds warnings but doesn't fix root problem).

## Impact on Yapit

EPUBs with separate notes files (common in professionally published books) lose all footnote content. The inline references survive as `<sup><a href="...">N</a></sup>` but the note definitions are dropped entirely.

## Workaround

Extract footnotes directly from the EPUB ZIP when pandoc fails to convert them. Two patterns:

1. **Old-style HTML** (Ubiquity): Notes present as `<a href="#backref" id="target">N.</a> text` — convert with regex.
2. **EPUB3 semantic** (Deep Utopia): Notes in `<ol class="footnotes">` with `epub:type="backlink"` — extract from ZIP, match to inline refs by ID.

---
status: done
completed: 2026-01-26
---

# Markdown Feature Extensions

Parser rewrite to support composable yap tags and unified audio chunk model.

## Design Decisions (2026-01-25 Planning Session)

### Tag Semantics

**yap-show** = show, don't speak
- Content goes to display, NOT to TTS
- Creates a "display-only zone" — nested content (including yap-speak) also excluded from TTS
- Use case: citations `[1, 2]`, author refs `(Smith et al.)`

**yap-speak** = speak, don't show (renamed from yap-alt for symmetry)
- Content goes to TTS, NOT to display
- NOT attached to preceding element — just independent content with TTS routing
- Use case: pronunciation for math, natural reading of displayed refs

**yap-cap** = caption container
- Provides caption for preceding image
- Supports full inline markdown: bold, links, math, yap-show, yap-speak

**Math** = always silent
- Display only, no TTS contribution on its own
- Adjacent yap-speak provides pronunciation: `$\alpha$<yap-speak>alpha</yap-speak>`

**Composition:** `<yap-show>X</yap-show><yap-speak>Y</yap-speak>` → display X, speak Y

### Block Model

Unified AudioChunk pattern for ALL blocks with audio:

```python
class AudioChunk(BaseModel):
    text: str
    audio_block_idx: int

class ParagraphBlock(BaseModel):
    html: str  # Contains <span data-audio-idx="N"> wrappers if split
    ast: list[InlineContent]
    audio_chunks: list[AudioChunk]  # 1+ chunks

class ImageBlock(BaseModel):
    src: str
    alt: str
    caption: str | None
    caption_html: str | None  # With span wrappers if split
    audio_chunks: list[AudioChunk]

class ListItem(BaseModel):
    html: str  # With span wrappers if split
    ast: list[InlineContent]
    audio_chunks: list[AudioChunk]
```

- Replaces `audio_block_idx: int | None` with `audio_chunks: list[AudioChunk]`
- Eliminates `visual_group_id` — HTML contains span wrappers directly
- ALL audio content respects max_block_chars (paragraphs, list items, captions)

### Frontend Impact

Frontend grouping logic (`visual_group_id`) removed. Transformer produces ready-to-render HTML with `data-audio-idx` spans baked in. Highlighting works the same way.

## Test Suite

Comprehensive tests in `tests/yapit/gateway/markdown/test_parser_v2.py`:
- **27 passing** (current behavior to preserve)
- **22 failing** (new features to implement)

Run: `uv run pytest tests/yapit/gateway/markdown/test_parser_v2.py -v`

## Implementation Plan

### Phase 1: yap-show + standalone yap-speak
Add `<yap-show>` handling and make yap-speak work independently of preceding math.

**Tests to pass:** TestYapShow::*, TestYapSpeak::test_standalone_yap_speak

### Phase 2: AudioChunk model
Replace single audio_block_idx with audio_chunks list on all block types.

**Tests to pass:** TestAudioChunkModel::*

### Phase 3: Universal splitting
Apply max_block_chars splitting to all audio content (paragraphs, list items, captions).
Generate span wrappers in HTML.

**Tests to pass:** TestUniversalSplitting::*

### Phase 4: Integration
Verify all compositions work together.

**Tests to pass:** TestFullDocument::*, TestTagComposition::*

## Footnotes (future, out of scope for current implementation)

**Status:** Not started

**Syntax:** `text[^1]` ... `[^1]: footnote content`

**Intended behavior (like blog posts):**
- `footnote_ref` (`[^1]` in text) — display-only marker, rendered as superscript link
- `footnote_content` (`[^1]: content`) — collected at footnote section at very bottom, after all content
- Links: ref links to content section, content can link back to ref position
- TTS: Footnote content has audio (read when navigating to footnote section); inline ref is silent

**Parser responsibility:**
- Detect `footnote_ref` and `footnote_content` with shared ID
- Parser does NOT validate matching — just detects both types
- Higher layer handles: display content even if no matching ref exists, hide ref if no matching content

**Implementation sketch:**
- Enable `mdit-py-plugins.footnote`
- Add `FootnoteRefInline` and `FootnoteBlock` to models
- Transformer handles `footnote_ref` and `footnote_anchor` node types

## Callouts (future, out of scope for current implementation)

**Status:** Not started

**Syntax:** GitHub/Obsidian style `> [!NOTE] Title`

**Behavior:**
- Just styled quote blocks with type indicator
- Title gets audio, body treated like regular blockquote content
- Frontend styling question mostly (different colors/icons per type)

**Implementation:**
- Detect `[!TYPE]` pattern in first line of blockquote
- Extract type and optional title
- Rest is nested blocks like regular blockquote

## Sources

**Key code files:**
- MUST READ: `yapit/gateway/markdown/transformer.py` — main rewrite target
- MUST READ: `yapit/gateway/markdown/models.py` — block type definitions (need AudioChunk)
- MUST READ: `tests/yapit/gateway/markdown/test_parser_v2.py` — spec for new behavior
- Reference: `frontend/src/components/structuredDocument.tsx` — will need updates for new model

**Related tasks:**
- [[2026-01-19-yap-show-tag]] — original yap-show design (superseded by this plan)
- [[2026-01-15-tts-annotation-syntax-pivot]] — historical context on yap tag design

## Done When

- [x] All tests in test_parser_v2.py pass (85 tests, expanded from original 49)
- [x] Existing tests in test_markdown.py still pass (or migrated)
- [x] Frontend renders split paragraphs correctly (no visual_group_id)
- [x] Gemini prompt updated: yap-alt → yap-speak
- [x] Footnotes implemented (was marked "out of scope" but completed)
- [x] Callouts implemented (was marked "out of scope" but completed)

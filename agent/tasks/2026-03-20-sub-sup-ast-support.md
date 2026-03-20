---
status: backlog
started: 2026-03-20
---

# Task: Add `<sub>` and `<sup>` AST support

HTML `<sub>` and `<sup>` tags pass through the markdown parser but get dropped by the transformer — no corresponding `InlineContent` type exists. This causes subscripts/superscripts to render as flat text (e.g., "x₁" → "x1").

Common in EPUBs that use HTML subscripts for inline math instead of MathML (e.g., `<i>a<sub>ij</sub></i>`). Also affects any document type where `<sub>`/`<sup>` appears in the markdown (sometimes arxiv/html, sometimes LLM).

## Approach

Same pattern as `StrongContent` / `EmphasisContent`:

1. **`yapit/gateway/markdown/models.py`**: Add `SubContent` and `SupContent` to `InlineContent` union. Both are wrappers with `content: list[InlineContent]`. TTS length = sum of children (subscripts are read as part of the word).

2. **`yapit/gateway/markdown/transformer.py`**: Handle `html_inline` tokens for `<sub>` and `<sup>` → new AST nodes.

3. **`frontend/src/components/inlineContent.tsx`**: Render as `<sub>` and `<sup>` HTML elements.

## Context

Discovered during EPUB support implementation. An EPUB math textbook (`preview-9781040281062`) uses 176 `<sub>` tags per chapter for inline variable subscripts — all rendered as flat text currently.

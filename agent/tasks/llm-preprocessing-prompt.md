---
status: idea
type: documentation
---

# LLM Preprocessing Prompt for Users

## Context

Our philosophy: Yapit parses and transcribes, we don't transform content. OCR does best-effort extraction.

For users with complex documents (LaTeX, heavy formatting, links, academic notation), we can provide a prompt they use with their own LLM to preprocess before uploading.

"Rewrite an paper / document to be more tts friendly which we can provide to copy paste in our UI as templates."
Maybe several different prompts for different use cases, or with toggles for choosing "I want math rewritten/skipped/..." vs "I want links removed" etc. for quick customization & copy paste.

## Use Cases

- LaTeX/math notation → readable prose ("x squared" instead of "x^2")
- Remove/describe hyperlinks ("link to Wikipedia" or just remove)
- Summarize/skip complex tables
- Clean up OCR artifacts
- Rewrite academic notation for audio clarity

## Prompt Draft

```
Transform this text for text-to-speech. Make it sound natural when read aloud:

1. Convert math/LaTeX to spoken form (e.g., "x^2" → "x squared", "∑" → "sum of")
2. Remove or describe hyperlinks (e.g., "[click here](url)" → "link to documentation")
3. Skip or summarize complex tables/figures
4. Expand abbreviations on first use
5. Keep the meaning intact, just optimize for listening

Text to transform:
---
[paste document here]
---
```

## Delivery Options

1. **Docs/FAQ**: Add to documentation with workflow recommendation
2. **In-app hint**: Show on upload page if OCR selected ("Having issues? Try preprocessing with an LLM first")
3. **Blog post**: "How to prepare complex documents for Yapit"

## Non-goals

- NOT integrating LLM into our pipeline (scope creep, cost, complexity)
- NOT building a "transform" feature
- Just providing a helpful prompt for power users

Previous considerations
- Math-to-Speech for TTS: Currently inline math is skipped for TTS. Options to consider:
  - Speech Rule Engine (SRE) / MathJax accessibility - converts MathML → speech strings
  - MathCAT - Rust-based alternative to SRE
  - LLM transcription - use cheap model to convert LaTeX → readable text (more flexible, natural-sounding)
  - Decision: Keep skipped for now


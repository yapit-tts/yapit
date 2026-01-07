---
status: active
started: 2025-01-06
---

# LLM Preprocessing Prompt for Users

## Context

Our philosophy: Yapit parses and transcribes, we don't transform content. OCR does best-effort extraction.

For users with complex documents (LaTeX, heavy formatting, links, academic notation), we can provide a prompt they use with their own LLM to preprocess before uploading.

"Rewrite an paper / document to be more tts friendly which we can provide to copy paste in our UI as templates."
Maybe several different prompts for different use cases, or with toggles for choosing "I want math rewritten/skipped/..." vs "I want links removed" etc. for quick customization & copy paste.

## Decisions

### Integration approach: Copy-paste (not OAuth/BYOK)

Considered alternatives:
- **OAuth to Claude/OpenAI** — Doesn't exist. Consumer subscriptions (Claude.ai, ChatGPT) are separate from API access. No OAuth flow to tap into user's credits.
- **BYOK (Bring Your Own Key)** — Possible but adds complexity: key storage security, validation, error handling, support burden. Benefit is saving ~3 clicks per document.

**Decision:** Copy-paste is the right tradeoff. Zero integration maintenance, works with any LLM (including local), ships immediately.

### UI placement: Help page with sidebar link

```
Sidebar footer:
│ 📋 Basic Plan   │  → /subscription
│ ❓ Help         │  → /help (new)
│ 👤 user@...   ▼ │  → Account (new), Sign out
```

Help page contains:
1. **Getting Started** — basic workflow
2. **Document Preprocessing** — prompt templates (this feature)
3. **FAQ**
4. **Tips** for different content types

This also addresses the need for a general help/onboarding page.

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


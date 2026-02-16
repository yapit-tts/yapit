---
status: active
started: 2026-02-09
---

# Task: README Rewrite for Public Launch

## Intent

Current README says "TODO very stale". The repo is being made public for a Gemini 3 hackathon submission. README is the first thing visitors see on GitHub.

## Style Reference

Model after [tinygrad/tinygrad](https://github.com/tinygrad/tinygrad) README:
- Centered logo/title at top
- Stars badge, CI badge
- One-liner tagline that positions the project
- Links row: Website | Docs | Discord (or whatever applies)
- Short, factual, hacker-oriented prose — NOT marketing fluff
- Comparisons to alternatives (factual, not snarky)
- Code/usage examples where it makes sense
- Minimal — don't pad with content that belongs in docs/

Tone: GitHub is for hackers. Factual. Honest. George Hotz energy. No "Welcome to Yapit!" cheerfulness. Show what it does, what makes it different, link out for the rest.

## Structure

1. **Centered header**: Logo (if we have one, otherwise skip), project name, tagline. Something like: "yapit: Listen to anything. Open-source TTS for documents, web pages, and text."
2. **Badges**: Stars, CI/deploy status
3. **Links row**: [Website](https://yapit.md) | [Architecture](docs/architecture.md) | [Knowledge Base](agent/knowledge/)
4. **What it does** (short paragraph): Paste a URL or upload a PDF → Gemini extracts it with vision → YOLO detects figures → listen with state-of-the-art voices. Free local synthesis via Kokoro WebGPU. Open source, self-hostable.
5. **What makes it different** (vs Speechify, NaturalReader, etc.): Better voices (Inworld 1.5, Kokoro). Gemini-powered extraction that actually handles LaTeX, figures, citations. Free browser-local TTS option. Open source (AGPL-3.0). No black-box extraction — custom `<yap-speak>`/`<yap-show>` tags route content between display and speech.
6. **Key features** (concise bullet list): Don't exhaustively list everything. Hit the highlights that matter.
7. **Self-hosting**: Brief. Reference .env.template, `make dev-cpu`. Details belong in docs.
8. **Development**: `make dev-cpu`, `make test-local`. Link to `agent/knowledge/dev-setup.md` for details. Mention the `agent/knowledge/` directory as the in-depth knowledge base (curated jointly with Claude during development).

No architecture section (that's `docs/architecture.md`). No tech stack section (that's docs). No license section (visible in repo sidebar). Keep it tight.

## Key Files

- READ FIRST: The tinygrad README (raw): `curl -sL https://raw.githubusercontent.com/tinygrad/tinygrad/master/README.md`
- READ: `docs/architecture.new.md` -- architecture overview (will be `docs/architecture.md` in final repo)
- READ: `CLAUDE.md` -- project overview section, codebase structure
- READ: `.env.template` -- required env vars for self-hosting context
- READ: `Makefile` -- available make targets

## Done When

- [ ] README.md rewritten following structure above
- [ ] Matches tinygrad energy — compact, factual, hacker-oriented
- [ ] Live demo URL (yapit.md) included
- [ ] No stale/incorrect information

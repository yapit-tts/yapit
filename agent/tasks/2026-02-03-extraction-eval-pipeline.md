---
status: active
started: 2026-02-03
---

# Task: Extraction Evaluation Pipeline

## Intent

Build a local pipeline for iterating on extraction prompts and website processing, with versioned artifacts and diffing. Two tracks:

1. **PDF Gemini extraction** — prompt changes, content ordering experiments (media-first vs text-first), YOLO in the loop. Requires Docker.
2. **Website content extraction** — trafilatura settings, JS rendering, free-path quality. Pure Python.

Both produce markdown artifacts per run, stored with a frozen prompt snapshot. Diffing is human-first (`oy` commands for changed files), with an optional background agent comparison via `claude -p`.

## Refactors Required (before pipeline)

1. **Decouple `GeminiExtractor` from `Settings`** — constructor takes `api_key: str` instead of `Settings`. Production code passes `settings.google_api_key`.
2. **Extract `_extract_website_content` from `documents.py`** → `yapit/gateway/document/website.py` as public `extract_website_content()`. API route imports and calls it.
3. **Add `prompt_path` override to `GeminiExtractor`** — `load_prompt()` currently hardcoded to `extraction.txt`. Add optional `prompt_path: Path | None` param; if provided, load from there instead.
4. **Add `media_first: bool` flag to `GeminiExtractor`** — controls content ordering in `_call_gemini_for_page()` (currently hardcoded PDF-first with TODO about it). Default `True` (current behavior).
5. **Delete `experiments/gemini-flash-doc-transform/`** — fully superseded.

## Pipeline Design

### Corpus definitions

```
scripts/eval/pdf_corpus.toml
scripts/eval/web_corpus.toml
```

PDF corpus: `[name]` sections with `url` and `pages` (0-indexed). ~20 pages across ~5-6 documents covering math, figures, footnotes, callouts, citations, references, title pages, code blocks.

Web corpus: `[name]` sections with `url`. Covering boilerplate-heavy sites, broken extractions, footnote-heavy pages.

### Runner: `scripts/eval/run.py`

Project script (imports from `yapit`, runs with `uv run`).

```bash
# PDF
uv run scripts/eval/run.py pdf
uv run scripts/eval/run.py pdf --prompt path/to/v10.txt --label v10-toc-fix
uv run scripts/eval/run.py pdf --only attention,cimc
uv run scripts/eval/run.py pdf --media-first        # A/B test content ordering
uv run scripts/eval/run.py pdf --batch               # batch API (future)

# Website
uv run scripts/eval/run.py web
uv run scripts/eval/run.py web --only sourcegraph-blog
```

Behavior:
- Downloads/caches source documents to `scripts/eval/docs/` (gitignored)
- For PDFs: instantiates `GeminiExtractor` with real Redis + ImageStorage, runs on specified pages, applies stitch + footnote dedup
- For websites: calls `extract_website_content()`
- Saves to `scripts/eval/runs/<label>/` with per-page outputs + stitched doc + meta + frozen prompt

### Artifact structure

```
scripts/eval/runs/
└── 2026-02-03_v9/
    ├── meta.toml       # prompt version, model, resolution, git hash, flags, cost
    ├── prompt.txt      # frozen snapshot of prompt used
    ├── pdf/
    │   ├── attention/
    │   │   ├── p0.md, p1.md, p4.md, p7.md
    │   │   └── stitched.md
    │   └── cimc/
    │       └── ...
    └── web/
        ├── sourcegraph-blog.md
        └── muzero.md
```

### Compare: `scripts/eval/compare.py`

```bash
uv run scripts/eval/compare.py runs/run_a runs/run_b
```

Stdout (immediate):
```
Changed (7/12):
  oy runs/run_a/pdf/attention/p1.md runs/run_b/pdf/attention/p1.md
  oy runs/run_a/pdf/cimc/p2.md runs/run_b/pdf/cimc/p2.md
  ...
Unchanged: 5

Agent comparison launched (session: abc123-def456)
  Resume: claude -r abc123-def456
```

The agent comparison runs in the background via `claude -p --output-format json --session-id <uuid>`. The prompt instructs it to:
- Read all changed file pairs
- Report EVERY difference (recall >>> precision) — even trivial ones like "2" → "two"
- Classify each as: structural, content, formatting, regression, improvement, neutral
- Write summary to `runs/run_b/comparison.md`
- Print session ID so user can `claude -r <id>` for follow-ups

## Sources

**Knowledge files:**
- [[document-processing]] — extraction pipeline, YOLO, Gemini integration

**Key code files:**
- MUST READ: `yapit/gateway/document/gemini.py` — GeminiExtractor, needs refactoring (Settings decoupling, prompt override, media-first flag)
- MUST READ: `yapit/gateway/document/extraction.py` — build_figure_prompt, stitch_pages, deduplicate_footnotes, load_prompt
- MUST READ: `yapit/gateway/document/processing.py` — ProcessorConfig, PageResult, ExtractedPage
- MUST READ: `yapit/gateway/api/v1/documents.py:429-466` — _extract_website_content to extract out
- MUST READ: `yapit/gateway/document/prompts/extraction.txt` — current v9 prompt
- Reference: `yapit/gateway/document/yolo_client.py` — YOLO queue interface
- Reference: `good-test-docs` — curated test document URLs
- Reference: `TODO` lines 72-83 — specific prompt improvements to test

**Related tasks:**
- [[2026-02-02-website-experience-improvements]] — trafilatura integration, Gemini webpage transform
- [[2026-01-26-gemini-batch-mode]] — batch API (future --batch flag)
- [[2026-01-14-ai-transform-retry-webpages]] — webpage Gemini transform prompt

## Done When

- [ ] Refactors: GeminiExtractor decoupled from Settings, prompt override, media-first flag
- [ ] Refactor: extract_website_content moved to own module
- [ ] Old experiment code deleted
- [ ] PDF + web corpus definitions with ~20 meaningful pages
- [ ] Runner produces versioned artifacts with frozen prompt snapshots
- [ ] Compare script prints oy commands for changed files
- [ ] Background agent comparison via claude -p with resumable session
- [ ] At least one successful comparative run (v9 baseline vs v9 re-run to establish variance)

## Considered & Rejected

- **PyMuPDF approximation instead of real YOLO** — deviates from production pipeline; if composability requires YOLO, the code should support it. Docker running is not a burden.
- **Automated quality scoring** — premature. Need human judgment first to calibrate what "good" looks like. The agent comparison is qualitative, not quantitative.
- **CI integration** — overkill. Local iteration tool.
- **Reference "golden" outputs** — Gemini output varies across runs. Diffing between runs is more useful than diffing against a frozen reference.
- **Tags in corpus TOML** — unnecessary complexity. We always run the full corpus (split by pdf/web). If subset needed, `--only` flag suffices.
- **Claude Code skill for diffing** — overengineered. `claude -r <session-id>` for follow-ups is simpler and more flexible than a skill with CLI flags.

## Discussion

- Batch API support is a future flag (`--batch`). Batch mode task is on a worktree, untested. Pipeline architecture supports it from day one since extraction is behind an async iterator interface regardless.
- For the media-first vs text-first A/B test: this is a code-level flag on GeminiExtractor, not a prompt change. The eval pipeline captures it in meta.toml so runs are distinguishable.
- Agent comparison prompt must emphasize recall over precision — better to flag a trivial change than miss a meaningful one. User can always dismiss; can't un-miss.

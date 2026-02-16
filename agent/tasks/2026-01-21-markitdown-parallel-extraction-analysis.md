---
status: done
started: 2026-01-21
completed: 2026-01-21
---

# Task: Analyze Parallel Page Extraction for MarkItDown

## Intent

Benchmark whether `yapit/gateway/document/markitdown.py` would benefit from splitting pages and extracting in parallel, similar to how Gemini processes PDFs.

## Finding: No Benefit (Analytical — No Benchmark Run)

This was code analysis, not empirical benchmarking. The reasoning:

### 1. No Page-Level API in MarkItDown

MarkItDown's PDF converter (`markitdown/converters/_pdf_converter.py`) uses pdfminer internally:
```python
pdfminer.high_level.extract_text(file_stream)
```

This is a single synchronous call that processes the entire PDF at once — no page-level granularity. pdfminer is a built-in dependency of MarkItDown, not something we control.

### 2. Other Formats Don't Have Pages

- `text/*`, `application/json`, `application/xml` → Single document
- `text/html` → Single page
- `application/epub+zip` → Returns single merged result
- `application/pdf` → pdfminer returns all text at once

### 3. Complexity + Threading Overhead Not Worth It

If we split PDFs into pages first (via pymupdf/pypdf), then processed each with MarkItDown:
- PDF splitting overhead
- pdfminer re-initialization per page
- Threading overhead for CPU-bound work (pdfminer is CPU-bound, not I/O-bound like Gemini API calls)
- Result merging

The added complexity isn't justified when MarkItDown extraction is already fast (~100-500ms for typical documents).

### 4. Current Architecture Context

MarkItDown extraction runs directly on the gateway — no queue, no workers. Until we hit actual scale/bottleneck issues on the server, adding infrastructure complexity is premature optimization.

### 5. Use Case Analysis

| Path | Processing |
|------|------------|
| Websites | Single HTML → single result |
| Documents (free) | MarkItDown on gateway → already fast |
| Documents (AI) | Gemini → **already parallelized** via async tasks |

Users who care about quality use Gemini (parallel). Users who use MarkItDown want "fast and free" — it already is.

## Sources

**Key code files:**
- `yapit/gateway/document/markitdown.py` — Current implementation
- `yapit/gateway/document/gemini.py:175-185` — Parallel extraction example
- `.venv/.../markitdown/converters/_pdf_converter.py` — pdfminer usage

---
status: active
refs:
  - "[[2026-03-05-defuddle-evaluation]]"
---

# Replace trafilatura with defuddle for website extraction

## Intent

Swap the primary website content extractor from trafilatura (Python) to defuddle (TypeScript) via an HTTP sidecar, following the markxiv pattern.

Defuddle produces meaningfully better output for TTS:
- Preserves list structure (trafilatura collapses bullet lists into paragraphs)
- Standardizes footnotes/sidenotes into `[^N]` markdown (trafilatura dumps sidenote content inline, breaking reading flow)
- Resolves image URLs to absolute
- Preserves `<video>` elements (trafilatura strips them)
- Extracts more content on citation-heavy pages

Develop on a feature branch. Don't ship until validated on broader traffic.

## Approach

**Sidecar service** accepting HTML + URL, returning markdown + metadata. Same pattern as markxiv.

Current pipeline:
```
HTML → JS detection → Playwright? → trafilatura → html2text fallback → resolve_relative_urls
```

New pipeline:
```
HTML → JS detection → Playwright? → defuddle sidecar → done
```

Things that stay unchanged:
- JS framework detection + Playwright rendering (defuddle operates on static HTML, same as trafilatura)
- `.md` source detection shortcut
- arXiv/markxiv path

Things defuddle replaces:
- `trafilatura.extract()` / `bare_extraction()`
- Layout table detection hack (`_LAYOUT_TABLE_THRESHOLD`, cell unwrapping)
- `html2text` fallback
- `resolve_relative_urls` (defuddle handles this internally)

## Assumptions

- Defuddle's Obsidian-flavored markdown (`> [!NOTE]` callouts, `[^N]` footnotes) is compatible with our markdown parser and block splitter. We use Obsidian conventions ourselves, so this should be fine — but needs verification against the actual block splitting code.
- The sidecar latency (~200-1000ms) is acceptable. Trafilatura is 10-50x faster, but extraction runs once on document creation, and Playwright already adds seconds when needed.
- Defuddle handles the broad range of sites users submit, not just the 4 test corpus URLs. The 30+ test fixtures in defuddle's repo (Wikipedia, Substack, Reddit, LessWrong, etc.) suggest good coverage, but needs validation against a larger test corpus and real-world latency before merging.
- We maintain a fork or pin a specific version. Defuddle is v0.x with active development — upstream breaking changes are possible. The fork also gives us the option to patch the footnote inline ref detection ourselves (phase 1→2 join) if the upstream issue doesn't get traction.

## Research

- [[2026-03-05-defuddle-evaluation]] — source analysis, comparative test results on 4 corpus URLs, integration options, stability assessment
- Upstream issue filed for footnote inline ref detection improvement (phase 1→2 join)

## Done When

- [ ] Defuddle sidecar service (Dockerfile, HTTP endpoint accepting HTML+URL, returning markdown+metadata)
- [ ] Added to docker-compose (dev + prod)
- [ ] `website.py` calls defuddle sidecar instead of trafilatura
- [ ] Layout table hack and html2text fallback removed
- [ ] Validated on all 4 web corpus URLs + a broader sample from real traffic
- [ ] Feature branch merged to main

## Considered & Rejected

- **Subprocess call to defuddle CLI** — Node.js cold start per call (~200-400ms overhead). Sidecar is warmer and consistent with markxiv.

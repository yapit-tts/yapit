---
name: defuddle-investigation
description: This skill should be used when the user asks to "investigate defuddle", "test defuddle on a site", "file a defuddle issue", "check defuddle output", "run a page through defuddle", or mentions extraction problems with a specific website URL that should work with the yapit TTS pipeline.
---

# Defuddle Investigation

Investigate defuddle extraction issues for specific websites, identify root causes in the defuddle source, and produce issue-ready markdown files.

## Repo & Resources

- **Defuddle source:** `~/repos/github/kepano/defuddle/` — pull before investigating (`git -C ~/repos/github/kepano/defuddle pull`)
- **GitHub:** `kepano/defuddle`
- **Live testing:** `https://defuddle.md/{domain}/{path}` — instant output, no local build needed
- **Our past issues:** `gh issue list -R kepano/defuddle --author MaxWolf-01 --state all`
- **Review past issues + fixes:** For each issue, fetch comments and linked commits to learn how the maintainer approaches fixes:
  ```
  gh issue view {N} -R kepano/defuddle --comments
  gh api -X GET repos/kepano/defuddle/commits/{sha} --jq '.files[].filename'
  gh api -X GET repos/kepano/defuddle/commits/{sha} --jq '.files[] | "\n=== \(.filename) ===\n\(.patch)"'
  ```

## Workflow

### 1. See the current output first

Check `https://defuddle.md/{url}` before anything else. This shows defuddle's latest output without needing a local build. Compare against the live website to spot issues visually.

### 2. Fetch raw HTML for deeper inspection

```bash
curl -sL "{url}" -o /tmp/page_under_test.html
```

Compare the raw HTML structure against the defuddle.md output. Look for: elements present in HTML but missing/mangled in output, content appearing that shouldn't be visible, code blocks rendered as inline text.

### 3. Test hidden-element hypotheses

When suspecting elements are hidden via CSS but leaking in defuddle output, use `scripts/check_hidden.js`:

```bash
node .claude/skills/defuddle-investigation/scripts/check_hidden.js /tmp/page_under_test.html ".suspect-class"
```

This checks whether defuddle's hidden-element detection (inline styles, class patterns, getComputedStyle) would catch the elements, and whether the cloneNode limitation applies.

### 4. Trace root causes in defuddle source

Pull and read the source at `~/repos/github/kepano/defuddle/src/`. Key files:

| File | Handles |
|------|---------|
| `elements/code.ts` | Code block recognition, language detection, content extraction |
| `elements/headings.ts` | Heading cleanup, permalink stripping |
| `elements/footnotes.ts` | Footnote detection and standardization |
| `standardize.ts` | Pre-processing: element transforms, attribute stripping, site-specific fixes (arXiv, Verso, etc.) |
| `defuddle.ts` | Main pipeline: cloning, hidden element removal, scoring, selector removal |
| `scoring.ts` | Content scoring, navigation detection, `isLikelyContent` |
| `markdown.ts` | Turndown rules for markdown conversion |
| `constants.ts` | Selectors, allowed attributes, `PRESERVE_ELEMENTS` |

**Known architectural constraint:** Defuddle operates on a `cloneNode(true)` copy of the document (defuddle.ts ~line 450). The clone has `defaultView: null`, so `getComputedStyle` never runs — even in a real browser. Only inline styles and class-name patterns are checked for hidden element detection. This means any element hidden purely via external CSS stylesheet will survive.

### 4. Verify hypotheses before writing

Every root cause claim must be tested. Write a verification script to `/tmp/` and run it with `uv run python /tmp/script.py` — this is auto-approved unlike `python -c` which prompts every time. Always use this pattern for verification, never inline `python -c`. Don't state something as fact until confirmed with code. Common verification patterns:

- Check if an element has inline styles: `el.getAttribute('style')`
- Check cloneNode behavior: clone the doc, check `clone.defaultView`
- Check what defuddle's selectors match: `document.querySelectorAll(selector)`
- Check computed styles on originals: `getComputedStyle(el).display`

### 5. Write one issue per problem

Each issue is a separate markdown file in the repo root: `defuddle-issue-{short-name}.md`

**Follow the style of past issues** (fetch them with `gh issue view {N} -R kepano/defuddle`). Structure:

```markdown
# {Concise title}

{1-2 sentence summary of the problem.}

## Example

{URL}

{HTML snippet showing the relevant structure}

**Expected:** {what should appear}

**Actual:** {what defuddle produces}

{Quantify: how many occurrences, how much of the page is affected.}

## Root cause

{Brief, verified explanation. Don't over-explain — the maintainer knows the codebase.}

## Fix direction

{Concrete suggestion, ideally referencing existing patterns in the codebase.}
```

**Don't:**
- Reference line numbers (they change)
- Over-explain how defuddle's internals work — the maintainer knows the codebase. Keep root cause and fix direction brief.
- Combine multiple issues into one file
- Write unverified root causes
- Quantify occurrences ("99 links on this page") or editorialize ("prose becomes unreadable") — the example speaks for itself
- Use `WebFetch` to check defuddle.md — it summarizes instead of returning raw output. Use `curl` instead.
- Frame issues around one site when the fix is general — if the bug affects any site with links inside inline code, say that in the title, not "Verso inline code links"
- File without checking whether the behavior is intentional. If it's consistent across all sites, it's probably by design (#240).

## When to also submit a PR

Always file an issue first. Additionally submit a PR only when ALL of these hold:

1. **Mechanical bugfix** — the fix follows directly from the root cause with no design judgment, no architectural tradeoffs, no "should this behave like X or Y" questions. If the fix involves taste or interpretation, the issue is enough — let the maintainer decide.
2. **Full codebase understanding** — you've read broadly enough to be confident the fix doesn't conflict with patterns elsewhere. You have 1M tokens of context — read the full `src/` directory, not just the file you're changing.
3. **The maintainer couldn't do it better** — if kepano would write the same fix given the same information, a PR saves him time. If he'd approach it differently with his deeper knowledge, the issue alone is more helpful.
4. **General over specific** — fixes should work for the next site with the same pattern, not just the ones you've seen. Hardcoding domains or site-specific patterns when a content-based heuristic would work is a red flag (#246).

### Matching the project's standards

- **Read defuddle's `CLAUDE.md`** for current conventions, build/test instructions, and pitfalls.
- **Study how our past issues were fixed** — fetch the closing commits for issues filed by MaxWolf-01 and read the patches. Look at commit message style, how fixtures are structured, what gets tested, how much code changes per fix.
- **Check recent merged PRs** (`gh pr list -R kepano/defuddle --state merged --limit 10`) to see what external contributions look like.

### PR workflow

1. Clone fresh from GitHub (not from local): `git clone https://github.com/kepano/defuddle.git /tmp/defuddle-pr`. Verify HEAD matches `gh api -X GET repos/kepano/defuddle/commits/main --jq '.sha[:7]'` — the fork remote or stale fetch can silently put you on old code.
2. `npm install && npm test` — verify clean baseline
3. Create a **minimal** fixture + expected output following the conventions in defuddle's `CLAUDE.md`. Minimal means: only the HTML structure needed to trigger the bug. Don't replicate the full page — strip everything that isn't load-bearing for the reproduction. Unrelated elements create noise in the expected output and can cause the test to break for reasons unrelated to the bug.
4. Run tests → must **fail** (proves the fixture exercises the bug)
5. Apply fix
6. Run tests → must **pass**, full suite must stay green
7. Finish the refactor — if your fix touches a pattern that exists in multiple places, apply it everywhere. A PR that fixes two of three call sites isn't "surgical," it's incomplete. (E.g. extracting a helper but leaving one inline copy "to be safe" just creates cleanup for the maintainer.)
8. Spawn a subagent to review your changes before submission
9. Add fork remote and push branch: `git remote add fork https://github.com/MaxWolf-01/defuddle.git` (the fork already exists from prior PRs), then `git push fork <branch>`. Open PR with `gh pr create`.
10. PR body should just be `Fixes #NNN` — the issue already has the explanation. Check recent merged PRs for kepano's style.
11. No Co-Authored-By lines for external contributions

Reuse `/tmp/test_defuddle.mjs` for all manual testing — the user has to approve each unique filename for `node` execution.

## Yapit Pipeline Context

Yapit runs defuddle in an isolated Node.js container (`docker/defuddle/app.js`) with a three-step cascade:

1. **Static fetch + linkedom** (default) — `Defuddle(html, url, { markdown: true })` via the `defuddle/node` API. No browser, no JS execution. Handles most content sites.
2. **Bot UA retry** — same as above but with a bot user agent. Some sites serve pre-rendered content to bots.
3. **Playwright fallback** — real Chromium browser, defuddle browser bundle injected via `context.addInitScript()`, `Defuddle(document, { url, markdown: true }).parseAsync()` in-page. Reserved for JS-rendered SPAs.

The `cloneNode` limitation applies to both static (linkedom) and Playwright paths — stylesheet-hidden elements leak regardless.

When investigating extraction issues, first check which path was used (container logs show `static:`, `static-bot:`, or `playwright:` prefix). If defuddle.md produces better output than yapit, the issue is likely in which extraction path was taken, not in defuddle itself.

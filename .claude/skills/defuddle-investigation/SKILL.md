---
name: Defuddle Investigation
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

Every root cause claim must be tested. Write a verification script to `/tmp/` and run it. Don't state something as fact until confirmed with code. Common verification patterns:

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
- Over-explain how defuddle's internals work
- Combine multiple issues into one file
- Write unverified root causes

## Yapit Pipeline Context

Yapit runs defuddle in a Playwright browser container (`docker/defuddle/app.py`). The browser bundle is injected via `context.add_init_script()`, then `Defuddle(document, { url, markdown: true }).parseAsync()` runs in-page. Despite being a real browser, the `cloneNode` limitation still applies — stylesheet-hidden elements leak in the yapit pipeline too.

To see yapit pipeline output for a URL, check the dashboard or process a document through the app.

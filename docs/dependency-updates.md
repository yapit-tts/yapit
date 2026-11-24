# Dependency Updates

## Defuddle Update Guide

npm package in `docker/defuddle/`. Dockerfile uses `npm ci`, so the lockfile must match package.json.

Dependabot (`.github/dependabot.yml`) keeps one PR open for the newest defuddle release that is at least 2 days old, replacing it when a newer one comes of age, and merges nothing itself. On any PR that changes the pinned version, the `defuddle bump check` workflow runs `scripts/defuddle-bump-check.mjs` and posts its report as a PR comment:

- **Supply chain.** The lockfile pins the registry's tarball, the package declares no install scripts, its provenance says upstream's release workflow built it from the version's tag, and its `dist/` rebuilds byte for byte from that commit.
- **Extraction A/B.** Both versions extract each page in `scripts/defuddle-ab-corpus.txt` from the same HTML. The comment lists which pages changed and shows the changes; the run's artifact holds every page's HTML, both outputs and the diffs.

What the check can't decide is whether each changed page is better or worse. Read the diffs against the upstream changes the comment links, then merge. To bump by hand, change the version in `package.json`, run `npm install --package-lock-only` in `docker/defuddle`, and run the script locally (`node scripts/defuddle-bump-check.mjs <old> <new>`) or push the branch as a PR.

The A/B covers the static path only. The Playwright path calls `new Defuddle(document, { url, markdown: true }).parseAsync()` on the browser bundle (`dist/index.full.js`), so a release that changes that API needs `app.js` checked by hand.

Playwright pins the Chromium build that ships in the production image (`npx playwright install`), so its version *is* our browser-security posture — bump it whenever Chromium majors move, not just when a Playwright feature is wanted. `browsers.json` in the Playwright tag says which Chromium a release carries:

```
curl -s https://raw.githubusercontent.com/microsoft/playwright/v<tag>/packages/playwright-core/browsers.json | jq -r '.browsers[] | select(.name=="chromium") | .browserVersion'
```

`npm install --package-lock-only` only re-resolves deps whose lockfile entry falls outside the declared range — a caret dep sitting at a now-vulnerable version stays put. Raise the floor in `package.json` (or `npm update <pkg>`) and re-run `npm audit` to confirm.

Verify all four extraction paths against the running container, not just one: static, static-bot (`github.com`), Playwright (any `text/plain` URL, e.g. an RFC or a raw GitHub file — the static path rejects the content type, Chromium renders it), and `html-direct` (POST `html` instead of `url`).

## Worker Images

Each worker image (`yapit/workers/{kokoro,yolo}/{cpu,gpu}/`) is its own uv project with a committed `uv.lock`, and its Dockerfile runs `uv sync --locked`, so a build installs exactly what was locked and a stale lock fails the build. To change a worker's dependencies, edit its `pyproject.toml` and run `uv lock` in that directory. `required-environments` lists the platforms the image is built for, so `uv lock` passes over any release without a wheel for each of them.

## PyAV and the LAME in it

The gateway encodes MP3 with the LAME that PyAV's binary wheel carries, built with the wheel's FFmpeg by [pyav-ffmpeg](https://github.com/PyAV-Org/pyav-ffmpeg) (`scripts/pkg.py` names each library and its version). That LAME bounds how long an MP3 file takes to build, and the wheels differ: on one core, five minutes of speech at the gateway's settings encode in 2.0 s with av 17.0.0 (LAME 3.100) and in 0.7 s with av 18.1.1 (bwlame 4.1.0, LAME 4.0 with the fixes of LAME 4.1's development backported). av 19.0.2 went back to LAME 3.101. So `pyproject.toml` holds av to 18.1.x. LAME is updated only by updating av, and av only to a release whose wheel carries a LAME at least as new as bwlame 4.1.0. This prints the LAME a release's wheel carries, `LAME4.1` for bwlame 4.1.0:

```
uv run --no-project --with av==<version> python -c "import av, pathlib, re; print({m.decode() for f in (pathlib.Path(av.__file__).parent.parent / 'av.libs').iterdir() for m in re.findall(rb'LAME\d+\.\d+', f.read_bytes())})"
```

Then time an MP3 build before and after the update with `experiments/audio_export_benchmark.py --format mp3`; its checks also say whether the file kept its duration, chapters and level.

## Adding New Dependencies

When adding new packages, verify license compatibility with AGPL-3.0. See [[licensing]] for verification commands and compatible licenses.

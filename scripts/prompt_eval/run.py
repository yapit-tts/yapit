#!/usr/bin/env python3
"""Extraction evaluation runner — compare Gemini extraction across prompt/config variants.

Examples (run from project root):

  # --- PDF extraction ---
  uv run scripts/prompt_eval/run.py pdf --ordering prompt-first     # extend/create run
  uv run scripts/prompt_eval/run.py pdf --ordering media-first      # images before prompt
  uv run scripts/prompt_eval/run.py pdf --ordering prompt-first --only attention,bigmath
  uv run scripts/prompt_eval/run.py pdf --extend v001               # backfill with new corpus entries
  uv run scripts/prompt_eval/run.py pdf --extend v001 --only newdoc
  uv run scripts/prompt_eval/run.py pdf --prompt path/to/new.txt --ordering prompt-first

  # --- Web extraction ---
  uv run scripts/prompt_eval/run.py web --ordering prompt-first
  uv run scripts/prompt_eval/run.py web --only sourcegraph,muzero
  uv run scripts/prompt_eval/run.py web --extend v001

  # --- Compare & List ---
  uv run scripts/prompt_eval/run.py compare v001 v002               # print diff commands
  uv run scripts/prompt_eval/run.py list                            # show all runs

  # --- Agent comparison (launches Claude to exhaustively diff two runs) ---
  uv run scripts/prompt_eval/compare.py pdf                         # auto-detect latest two pdf runs
  uv run scripts/prompt_eval/compare.py pdf v001 v002               # compare specific runs
  uv run scripts/prompt_eval/compare.py pdf v001 v002 --no-agent    # diff commands only, skip Claude

  # --- Re-extract a document (delete + re-run) ---
  rm -rf scripts/prompt_eval/runs/pdf/v001/attention
  uv run scripts/prompt_eval/run.py pdf --extend v001 --only attention
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import groupby
from pathlib import Path
from typing import Annotated, Literal

import httpx
import tyro
from redis.asyncio import Redis

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from yapit.gateway.document.extraction import deduplicate_footnotes, stitch_pages  # noqa: E402
from yapit.gateway.document.gemini import GeminiExtractor  # noqa: E402

SCRIPT_DIR = Path(__file__).parent
DOCS_DIR = SCRIPT_DIR / "docs"
RUNS_DIR = SCRIPT_DIR / "runs"

TRACK_CONFIG = {
    "pdf": {
        "corpus": SCRIPT_DIR / "pdf_corpus.toml",
        "default_prompt": PROJECT_ROOT / "yapit" / "gateway" / "document" / "prompts" / "extraction.txt",
    },
    "web": {
        "corpus": SCRIPT_DIR / "web_corpus.toml",
        "default_prompt": PROJECT_ROOT / "yapit" / "gateway" / "document" / "prompts" / "web_extraction.txt",
    },
}


# -- CLI -------------------------------------------------------------------


@dataclass
class Pdf:
    """Run PDF extraction. Auto-extends matching runs; only extracts new docs.

    Corpus entries support both URLs and local files:
      [mydoc]
      url = "https://example.com/paper.pdf"   # downloaded + cached
      path = "/absolute/path/to/local.pdf"     # used directly
      pages = [0, 1, 2]
    """

    only: str | None = None
    """Comma-separated document names to process (default: all in corpus)."""

    prompt: Path | None = None
    """Extraction prompt file (default: production prompt)."""

    ordering: Literal["media-first", "prompt-first"] = "prompt-first"
    """Content ordering sent to Gemini. Different ordering = separate run."""

    extend: str | None = None
    """Extend a specific existing run (e.g. 'v001'). Uses that run's frozen
    config; --ordering and --prompt are ignored."""


@dataclass
class Web:
    """Run web extraction. Auto-extends matching runs; only extracts new docs."""

    only: str | None = None
    """Comma-separated document names to process (default: all in corpus)."""

    prompt: Path | None = None
    """Extraction prompt file (default: production prompt)."""

    ordering: Literal["media-first", "prompt-first"] = "prompt-first"
    """Content ordering sent to Gemini. Different ordering = separate run."""

    extend: str | None = None
    """Extend a specific existing run (e.g. 'v001'). Uses that run's frozen
    config; --ordering and --prompt are ignored."""


@dataclass
class Compare:
    """Print diff commands between two runs.

    Example: uv run scripts/prompt_eval/run.py compare v001 v002
    """

    run_a: Annotated[str, tyro.conf.Positional]
    """First run, e.g. 'v001'."""

    run_b: Annotated[str, tyro.conf.Positional]
    """Second run, e.g. 'v002'."""


@dataclass
class List:
    """List all runs with config summary.

    Add description = 'my note' to a run's meta.toml to annotate it.
    """

    pass


# -- Shared infrastructure -------------------------------------------------


def doc_output(run_dir: Path, name: str, track: str) -> Path:
    """Where a document's extraction output lives."""
    if track == "pdf":
        return run_dir / name / "stitched.md"
    return run_dir / f"{name}.md"


def list_docs(run_dir: Path, track: str) -> list[str]:
    """Enumerate extracted documents in a run directory."""
    if track == "pdf":
        return sorted(d.name for d in run_dir.iterdir() if d.is_dir() and (d / "stitched.md").exists())
    return sorted(p.stem for p in run_dir.glob("*.md"))


async def download_file(url: str, dest: Path) -> None:
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
    print(f"  Downloaded: {dest.name}")


async def resolve_pdf(name: str, doc: dict) -> Path:
    """Get PDF — download from URL or use local path."""
    if "path" in doc:
        p = Path(doc["path"])
        assert p.exists(), f"{name}: local file not found: {p}"
        return p
    dest = DOCS_DIR / f"{name}.pdf"
    await download_file(doc["url"], dest)
    return dest


def get_git_hash() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def read_meta(path: Path) -> dict:
    """Read meta.toml, tolerant of old Python-repr booleans."""
    text = path.read_text()
    text = text.replace(" = True\n", " = true\n").replace(" = False\n", " = false\n")
    return tomllib.loads(text)


def toml_value(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return repr(v)


def compute_run_id(prompt_path: Path, media_first: bool) -> str:
    """Run identity = prompt content + content ordering."""
    prompt_hash = hashlib.sha256(prompt_path.read_bytes()).hexdigest()[:8]
    order = "media" if media_first else "prompt"
    return f"{prompt_hash}_{order}"


def find_run(track: str, prompt_content: str, media_first: bool) -> Path | None:
    """Find existing run matching config (frozen prompt content + media_first)."""
    track_dir = RUNS_DIR / track
    if not track_dir.exists():
        return None
    for run_dir in sorted(track_dir.glob("v*")):
        prompt_file = run_dir / "prompt.txt"
        meta_file = run_dir / "meta.toml"
        if not prompt_file.exists() or not meta_file.exists():
            continue
        meta = read_meta(meta_file)
        if meta.get("media_first") == media_first and prompt_file.read_text() == prompt_content:
            return run_dir
    return None


def get_next_version(track: str) -> int:
    track_dir = RUNS_DIR / track
    if not track_dir.exists():
        return 1
    versions = []
    for p in track_dir.glob("v*"):
        try:
            versions.append(int(p.name[1:]))
        except ValueError:
            continue
    return max(versions, default=0) + 1


def create_run_dir(track: str) -> Path:
    version = get_next_version(track)
    run_dir = RUNS_DIR / track / f"v{version:03d}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def write_meta(run_dir: Path, track: str, prompt_path: Path, media_first: bool) -> None:
    """Write/update meta.toml — documents list derived from filesystem."""
    meta_file = run_dir / "meta.toml"
    existing = read_meta(meta_file) if meta_file.exists() else {}

    meta = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_hash": get_git_hash(),
        "prompt_path": existing.get("prompt_path", str(prompt_path)),
        "media_first": media_first,
        "track": track,
        "documents": list_docs(run_dir, track),
        "run_id": compute_run_id(prompt_path, media_first),
    }
    if desc := existing.get("description"):
        meta["description"] = desc
    meta_file.write_text("\n".join(f"{k} = {toml_value(v)}" for k, v in meta.items()))


def prepare_run(
    track: str,
    corpus: dict,
    only: list[str] | None,
    prompt_path: Path,
    media_first: bool,
    extend_dir: Path | None = None,
) -> tuple[Path, dict]:
    """Find/create run, freeze prompt, filter to un-extracted docs.

    Returns (run_dir, to_extract) where to_extract is the subset of corpus
    that still needs extraction.
    """
    if only:
        corpus = {k: v for k, v in corpus.items() if k in only}
        assert corpus, f"No matching documents for --only {only}"

    if extend_dir:
        run_dir = extend_dir
        print(f"Extending: {track}/{run_dir.name}")
    else:
        prompt_content = prompt_path.read_text()
        run_dir = find_run(track, prompt_content, media_first)
        if run_dir:
            print(f"Extending: {track}/{run_dir.name}")
        else:
            run_dir = create_run_dir(track)
            print(f"New run: {track}/{run_dir.name}")

    if not (run_dir / "prompt.txt").exists():
        (run_dir / "prompt.txt").write_text(prompt_path.read_text())

    to_extract = {}
    for name, doc in corpus.items():
        if doc_output(run_dir, name, track).exists():
            print(f"  {name}: exists, skipping")
        else:
            to_extract[name] = doc

    return run_dir, to_extract


# -- PDF extraction --------------------------------------------------------


async def run_pdf_extraction(
    corpus: dict,
    only: list[str] | None,
    prompt_path: Path,
    media_first: bool,
    extend_dir: Path | None = None,
) -> Path:
    api_key = os.environ.get("GOOGLE_API_KEY")
    assert api_key, "GOOGLE_API_KEY not set"

    corpus = {k: v for k, v in corpus.items() if v.get("pages")}
    assert corpus, "No documents with pages defined"

    run_dir, to_extract = prepare_run("pdf", corpus, only, prompt_path, media_first, extend_dir)

    if not to_extract:
        print("All documents already extracted.")
        write_meta(run_dir, "pdf", prompt_path, media_first)
        return run_dir

    redis = Redis.from_url("redis://localhost:6379")

    class DummyImageStorage:
        async def store(self, content_hash, filename, data, mime_type):
            return f"file://{content_hash}/{filename}"

        async def exists(self, content_hash):
            return False

    extractor = GeminiExtractor(
        api_key=api_key,
        redis=redis,
        image_storage=DummyImageStorage(),
        prompt_path=prompt_path,
        media_first=media_first,
    )

    total_cost = 0.0
    total_pages = 0

    for name, doc in to_extract.items():
        pages = doc["pages"]
        notes = doc.get("notes", "")

        print(f"\n{name}: {len(pages)} pages")
        if notes:
            print(f"  ({notes})")

        pdf_path = await resolve_pdf(name, doc)
        content = pdf_path.read_bytes()
        content_hash = hashlib.sha256(content).hexdigest()[:16]

        doc_dir = run_dir / name
        doc_dir.mkdir(exist_ok=True)

        page_results: dict[int, str] = {}
        async for result in extractor.extract(
            content=content,
            content_type="application/pdf",
            content_hash=content_hash,
            pages=pages,
        ):
            if result.page is None:
                print(f"  Page {result.page_idx}: FAILED")
                continue

            page_results[result.page_idx] = result.page.markdown

            token_equiv = result.input_tokens + (result.output_tokens + result.thoughts_tokens) * 6
            cost = token_equiv * 0.5 / 1_000_000
            total_cost += cost
            total_pages += 1

            print(f"  Page {result.page_idx}: {len(result.page.markdown)} chars, ${cost:.4f}")

        if page_results:
            deduped = deduplicate_footnotes(page_results)
            ordered = [deduped[i] for i in sorted(deduped.keys())]
            stitched = stitch_pages(ordered)
            (doc_dir / "stitched.md").write_text(stitched)

    await redis.aclose()
    write_meta(run_dir, "pdf", prompt_path, media_first)

    print(f"\n{'=' * 50}")
    print(f"Extracted: {total_pages} pages, ${total_cost:.4f}")
    print(f"Output: {run_dir}")

    return run_dir


# -- Web extraction --------------------------------------------------------


async def run_web_extraction(
    corpus: dict,
    only: list[str] | None,
    prompt_path: Path,
    media_first: bool,
    extend_dir: Path | None = None,
) -> Path:
    run_dir, to_extract = prepare_run("web", corpus, only, prompt_path, media_first, extend_dir)

    if not to_extract:
        print("All documents already extracted.")
        write_meta(run_dir, "web", prompt_path, media_first)
        return run_dir

    from yapit.gateway.document.website import extract_website_content

    for name, doc in to_extract.items():
        url = doc["url"]
        notes = doc.get("notes", "")

        print(f"\n{name}: {url}")
        if notes:
            print(f"  ({notes})")

        html_path = DOCS_DIR / f"{name}.html"
        await download_file(url, html_path)
        content = html_path.read_bytes()

        markdown, method = await extract_website_content(content, url, markxiv_url=None)
        print(f"  Method: {method}, {len(markdown)} chars")

        (run_dir / f"{name}.md").write_text(markdown)

    write_meta(run_dir, "web", prompt_path, media_first)

    print(f"\n{'=' * 50}")
    print(f"Output: {run_dir}")

    return run_dir


# -- Compare & List --------------------------------------------------------


def find_run_dir(name: str) -> tuple[Path, str]:
    """Resolve run name (e.g. 'v001') to (path, track). Auto-detects track."""
    for track in ("pdf", "web"):
        candidate = RUNS_DIR / track / name
        if candidate.exists():
            return candidate, track
    raise AssertionError(f"Run not found: {name} (checked pdf/, web/)")


def print_diff_commands(dir_a: Path, dir_b: Path, track: str) -> None:
    all_docs: set[str] = set()
    for d in (dir_a, dir_b):
        all_docs |= set(list_docs(d, track))

    changed, only_a, only_b, identical = [], [], [], 0
    for doc in sorted(all_docs):
        fa, fb = doc_output(dir_a, doc, track), doc_output(dir_b, doc, track)
        has_a, has_b = fa.exists(), fb.exists()
        if has_a and has_b:
            if fa.read_text() != fb.read_text():
                changed.append((fa, fb))
            else:
                identical += 1
        elif has_a:
            only_a.append(doc)
        else:
            only_b.append(doc)

    if changed:
        print(f"\nDifferent ({len(changed)}):")
        for a, b in changed:
            print(f"  oy {a} {b}")
    if only_a:
        print(f"\nOnly in {dir_a.name} ({len(only_a)}): {', '.join(only_a)}")
    if only_b:
        print(f"\nOnly in {dir_b.name} ({len(only_b)}): {', '.join(only_b)}")
    if identical:
        print(f"\nIdentical: {identical}")
    if not changed and not only_a and not only_b:
        print("Runs are identical.")


def print_runs_list() -> None:
    if not RUNS_DIR.exists():
        print("No runs yet.")
        return

    for track_dir in sorted(RUNS_DIR.iterdir()):
        if not track_dir.is_dir():
            continue
        track = track_dir.name

        runs: list[tuple[str, dict, str | None]] = []
        for run_dir in sorted(track_dir.glob("v*")):
            meta_file = run_dir / "meta.toml"
            if not meta_file.exists():
                continue
            meta = read_meta(meta_file)
            prompt_file = run_dir / "prompt.txt"
            prompt_hash = hashlib.sha256(prompt_file.read_bytes()).hexdigest()[:8] if prompt_file.exists() else None
            runs.append((run_dir.name, meta, prompt_hash))

        if not runs:
            continue

        print(f"\n{track}/")

        for prompt_hash, group in groupby(runs, key=lambda r: r[2]):
            group_list = list(group)
            label = prompt_hash or "unknown"
            prompt_path = group_list[0][1].get("prompt_path", "")
            prompt_name = Path(prompt_path).name if prompt_path else "?"
            print(f"  prompt: {prompt_name} ({label})")

            for name, meta, _ in group_list:
                docs = meta.get("documents", [])
                order = "media-first" if meta.get("media_first", True) else "prompt-first"
                desc = meta.get("description", "")
                desc_str = f'  "{desc}"' if desc else ""
                print(f"    {name}  {order:>12}  {len(docs)} docs{desc_str}")


# -- Main ------------------------------------------------------------------


Cmd = (
    Annotated[Pdf, tyro.conf.subcommand(name="pdf", prefix_name=False)]
    | Annotated[Web, tyro.conf.subcommand(name="web", prefix_name=False)]
    | Annotated[Compare, tyro.conf.subcommand(name="compare", prefix_name=False)]
    | Annotated[List, tyro.conf.subcommand(name="list", prefix_name=False)]
)


def resolve_extraction_config(
    cmd: Pdf | Web,
    track: str,
) -> tuple[dict, list[str] | None, Path, bool, Path | None]:
    """Resolve CLI flags to (corpus, only, prompt_path, media_first, extend_dir)."""
    cfg = TRACK_CONFIG[track]
    corpus_file = cfg["corpus"]
    assert corpus_file.exists(), f"{corpus_file} not found"
    corpus = tomllib.loads(corpus_file.read_text())
    only = cmd.only.split(",") if cmd.only else None

    if cmd.extend:
        run_dir = RUNS_DIR / track / cmd.extend
        assert run_dir.exists(), f"Run not found: {run_dir}"
        assert (run_dir / "prompt.txt").exists(), f"No prompt.txt in {run_dir}"
        meta = read_meta(run_dir / "meta.toml")
        prompt_path = run_dir / "prompt.txt"
        media_first = meta["media_first"]
        if cmd.prompt or cmd.ordering != "prompt-first":
            print(f"Note: --extend uses frozen config from {cmd.extend}; ignoring --ordering/--prompt")
        return corpus, only, prompt_path, media_first, run_dir

    prompt_path = cmd.prompt or cfg["default_prompt"]
    assert prompt_path.exists(), f"Prompt not found: {prompt_path}"
    media_first = cmd.ordering == "media-first"
    return corpus, only, prompt_path, media_first, None


def main() -> None:
    cmd = tyro.cli(Cmd, description=__doc__)

    if isinstance(cmd, (Pdf, Web)):
        track = "pdf" if isinstance(cmd, Pdf) else "web"
        corpus, only, prompt_path, media_first, extend_dir = resolve_extraction_config(cmd, track)
        extract_fn = run_pdf_extraction if track == "pdf" else run_web_extraction
        asyncio.run(
            extract_fn(
                corpus=corpus,
                only=only,
                prompt_path=prompt_path,
                media_first=media_first,
                extend_dir=extend_dir,
            )
        )

    elif isinstance(cmd, Compare):
        dir_a, track_a = find_run_dir(cmd.run_a)
        dir_b, track_b = find_run_dir(cmd.run_b)
        assert track_a == track_b, f"Cannot compare across tracks: {track_a} vs {track_b}"
        print_diff_commands(dir_a, dir_b, track_a)

    elif isinstance(cmd, List):
        print_runs_list()


if __name__ == "__main__":
    main()

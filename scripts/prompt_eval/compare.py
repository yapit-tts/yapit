#!/usr/bin/env python3
"""Compare extraction runs and optionally launch agent analysis.

Usage:
    uv run scripts/prompt_eval/compare.py runs/run_a runs/run_b
    uv run scripts/prompt_eval/compare.py  # auto-detect latest two runs
"""

import argparse
import subprocess
import sys
import uuid
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
RUNS_DIR = SCRIPT_DIR / "runs"

PDF_AGENT_PROMPT = """You are comparing Gemini document extraction outputs between two runs.

## File Structure

```
scripts/prompt_eval/runs/pdf/
├── {run_a_name}/
│   ├── meta.toml        # run params (media_first, documents, run_id)
│   ├── prompt.txt       # the Gemini extraction prompt used
│   └── <docname>/
│       └── stitched.md  # extracted + stitched output
└── {run_b_name}/
    └── (same structure)
```

## Corpus

The corpus definition below shows which documents/pages were extracted. The `notes` are for human reference about what each document tests — use them as hints but do a full exhaustive diff regardless.

<corpus>
{corpus}
</corpus>

## Your Task

Compare runs `{run_a_name}` (older) vs `{run_b_name}` (newer).

1. First read `meta.toml` and `prompt.txt` from both runs to understand:
   - What prompt was used (may be identical or different)
   - What settings differ (e.g., `media_first` = content ordering)

2. Then read the `stitched.md` files and compare them exhaustively.

3. Report ALL differences — recall > precision. Flag even trivial changes; I'll decide what matters.

4. Judge quality based on what the prompt asks for. If the prompt says to do X and one run does X better, that's an improvement.

## Output Format

For each document with differences:
- **Document**: name
- **Changes**: List each difference with quoted snippets from both versions
- **Classification**: regression / improvement / neutral (per the prompt's intent)

Then a summary:
- Total differences found
- Clear regressions
- Clear improvements
- Patterns observed

Runs to compare:
- A (older): {run_a}
- B (newer): {run_b}
"""


def find_latest_runs(track: str, n: int = 2) -> list[Path]:
    """Find the n most recent runs (by version number) for a track."""
    track_dir = RUNS_DIR / track
    if not track_dir.exists():
        return []
    runs = []
    for p in track_dir.glob("v*"):
        try:
            runs.append((int(p.name[1:]), p))
        except ValueError:
            continue
    runs.sort(reverse=True)
    return [p for _, p in runs[:n]]


def detect_track(run_path: Path) -> str | None:
    """Detect track from run path (e.g., runs/pdf/v001 -> pdf)."""
    # Path should be runs/<track>/v###
    if run_path.parent.parent == RUNS_DIR:
        return run_path.parent.name
    return None


def collect_changed_files(run_a: Path, run_b: Path, track: str) -> list[tuple[Path | None, Path]]:
    """Collect changed files between runs. Returns (file_a, file_b)."""
    changed = []

    if track == "pdf":
        # Compare stitched.md per document
        for doc_dir in sorted(run_b.iterdir()):
            if not doc_dir.is_dir():
                continue
            file_b = doc_dir / "stitched.md"
            if not file_b.exists():
                continue
            file_a = run_a / doc_dir.name / "stitched.md"
            if file_a.exists():
                if file_a.read_text() != file_b.read_text():
                    changed.append((file_a, file_b))
            else:
                changed.append((None, file_b))
    else:
        # Web: compare all .md files directly
        for file_b in sorted(run_b.glob("*.md")):
            file_a = run_a / file_b.name
            if file_a.exists():
                if file_a.read_text() != file_b.read_text():
                    changed.append((file_a, file_b))
            else:
                changed.append((None, file_b))

    return changed


def print_diff_commands(changed: list[tuple[Path | None, Path]]) -> None:
    """Print oy commands for changed files."""
    if not changed:
        print("No changed files.")
        return

    print(f"Changed ({len(changed)}):")
    for file_a, file_b in changed:
        if file_a:
            print(f"  oy {file_a} {file_b}")
        else:
            print(f"  # NEW: {file_b}")


PDF_CORPUS_FILE = SCRIPT_DIR / "pdf_corpus.toml"
WEB_CORPUS_FILE = SCRIPT_DIR / "web_corpus.toml"


def run_agent_comparison(run_a: Path, run_b: Path, track: str) -> str:
    """Run claude -p for agent comparison. Returns session ID."""
    session_id = str(uuid.uuid4())

    # Load corpus
    if track == "pdf":
        corpus = PDF_CORPUS_FILE.read_text() if PDF_CORPUS_FILE.exists() else "(corpus file not found)"
        prompt = PDF_AGENT_PROMPT.format(
            run_a=run_a,
            run_b=run_b,
            run_a_name=run_a.name,
            run_b_name=run_b.name,
            corpus=corpus,
        )
    else:
        # TODO: web prompt when needed
        corpus = WEB_CORPUS_FILE.read_text() if WEB_CORPUS_FILE.exists() else "(corpus file not found)"
        prompt = PDF_AGENT_PROMPT.format(
            run_a=run_a,
            run_b=run_b,
            run_a_name=run_a.name,
            run_b_name=run_b.name,
            corpus=corpus,
        )

    cmd = [
        "claude",
        "-p",
        "--output-format",
        "text",
        "--session-id",
        session_id,
        prompt,
    ]

    # Run and capture output
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=SCRIPT_DIR.parent.parent,  # project root
    )

    # Print the response
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)

    return session_id


def main():
    parser = argparse.ArgumentParser(description="Compare extraction runs")
    parser.add_argument(
        "track", nargs="?", choices=["pdf", "web"], help="Track to compare (auto-detects if runs specified)"
    )
    parser.add_argument("run_a", type=Path, nargs="?", help="First run directory (older)")
    parser.add_argument("run_b", type=Path, nargs="?", help="Second run directory (newer)")
    parser.add_argument("--no-agent", action="store_true", help="Skip agent comparison")
    args = parser.parse_args()

    def resolve_run(name: Path, track: str) -> Path:
        """Resolve short name (v001) to full path using track."""
        if name.exists():
            return name
        candidate = RUNS_DIR / track / name.name
        if candidate.exists():
            return candidate
        return name  # let the existence check below produce the error

    # Determine track and runs
    if args.run_a and args.run_b:
        run_a, run_b = args.run_a, args.run_b
        track = detect_track(run_b) or args.track
        if not track:
            print("Error: Could not detect track. Specify track or use runs/pdf/v### paths.", file=sys.stderr)
            sys.exit(1)
        run_a, run_b = resolve_run(run_a, track), resolve_run(run_b, track)
    elif args.track:
        latest = find_latest_runs(args.track, 2)
        if len(latest) < 2:
            print(f"Error: Need at least 2 {args.track} runs to compare.", file=sys.stderr)
            sys.exit(1)
        run_a, run_b = latest[1], latest[0]  # older first, newer second
        track = args.track
        print(f"Auto-detected {track} runs:")
        print(f"  A (older): {run_a.name}")
        print(f"  B (newer): {run_b.name}")
    else:
        # Try pdf first, then web
        for t in ["pdf", "web"]:
            latest = find_latest_runs(t, 2)
            if len(latest) >= 2:
                run_a, run_b = latest[1], latest[0]
                track = t
                print(f"Auto-detected {track} runs:")
                print(f"  A (older): {run_a.name}")
                print(f"  B (newer): {run_b.name}")
                break
        else:
            print("Error: Need at least 2 runs to compare. Run extractions first.", file=sys.stderr)
            sys.exit(1)

    if not run_a.exists():
        print(f"Error: {run_a} not found", file=sys.stderr)
        sys.exit(1)
    if not run_b.exists():
        print(f"Error: {run_b} not found", file=sys.stderr)
        sys.exit(1)

    # Collect and print changed files
    changed = collect_changed_files(run_a, run_b, track)
    print_diff_commands(changed)

    # Run agent comparison
    if not args.no_agent and changed:
        print()
        session_id = run_agent_comparison(run_a, run_b, track)
        print()
        print(f"ccr {session_id}")


if __name__ == "__main__":
    main()

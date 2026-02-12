# /// script
# requires-python = ">=3.12"
# dependencies = ["pymupdf>=1.25", "tomli>=2.0"]
# ///
"""PyMuPDF extraction quality eval tool.

Usage:
  uv run experiments/pymupdf_eval/run.py fetch           # Download remote PDFs
  uv run experiments/pymupdf_eval/run.py extract baseline # Run baseline extraction
  uv run experiments/pymupdf_eval/run.py extract v001     # Run named approach
  uv run experiments/pymupdf_eval/run.py compare baseline v001
  uv run experiments/pymupdf_eval/run.py compare baseline v001 --doc attention
"""

import difflib
import shutil
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

import pymupdf
import tomli

EVAL_DIR = Path(__file__).parent
CORPUS_TOML = EVAL_DIR / "corpus.toml"
CORPUS_DIR = EVAL_DIR / "corpus"
RUNS_DIR = EVAL_DIR / "runs"
APPROACHES_DIR = EVAL_DIR / "approaches"


# ---------------------------------------------------------------------------
# Corpus loading
# ---------------------------------------------------------------------------


def load_corpus() -> dict:
    with open(CORPUS_TOML, "rb") as f:
        raw = tomli.load(f)
    return raw["docs"]


def resolve_pdf_path(name: str, doc: dict) -> Path:
    if "path" in doc:
        return Path(doc["path"])
    return CORPUS_DIR / f"{name}.pdf"


def fetch_corpus():
    """Download remote PDFs that aren't already cached."""
    CORPUS_DIR.mkdir(exist_ok=True)
    corpus = load_corpus()
    for name, doc in corpus.items():
        url = doc.get("url")
        if not url:
            continue
        dest = CORPUS_DIR / f"{name}.pdf"
        if dest.exists():
            print(f"  {name}: already cached")
            continue
        print(f"  {name}: fetching {url} ...")
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 (pymupdf-eval)"})
        try:
            with urlopen(req, timeout=60) as resp:
                dest.write_bytes(resp.read())
            print(f"  {name}: saved ({dest.stat().st_size / 1024:.0f} KB)")
        except Exception as e:
            print(f"  {name}: FAILED ({e})")
            dest.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Extraction approaches
# ---------------------------------------------------------------------------


def approach_baseline(page: pymupdf.Page) -> str:
    """Current production extraction: get_text("text")."""
    return page.get_text().replace("\x00", "")


def approach_dict_filter(page: pymupdf.Page) -> str:
    """Filter non-horizontal text via dict mode direction vectors."""
    d = page.get_text("dict")
    blocks = []
    for block in d["blocks"]:
        if block["type"] != 0:  # skip image blocks
            continue
        lines = []
        for line in block["lines"]:
            dx, dy = line.get("dir", (1, 0))
            if abs(dx) < 0.5:
                continue  # skip rotated text (>60° from horizontal)
            text = "".join(span["text"] for span in line["spans"])
            lines.append(text)
        if lines:
            blocks.append("\n".join(lines))
    return "\n\n".join(blocks).replace("\x00", "")


def approach_dict_filter_images(page: pymupdf.Page) -> str:
    """dict_filter + suppress SHORT text blocks that are fully inside image regions.

    Only suppresses blocks where:
    - The block is fully contained within an image rect
    - The block has very little text (< 80 chars) — likely a label, not body text
    This avoids killing body text on pages with full-page background images.
    """
    image_rects = []
    for img in page.get_images(full=True):
        rects = page.get_image_rects(img[0])
        image_rects.extend(rects)

    d = page.get_text("dict")
    blocks = []
    for block in d["blocks"]:
        if block["type"] != 0:
            continue

        block_rect = pymupdf.Rect(block["bbox"])
        block_text_len = sum(len(span["text"]) for line in block["lines"] for span in line["spans"])
        # Only suppress short blocks fully inside an image
        if block_text_len < 80:
            fully_in_image = any(r.contains(block_rect) for r in image_rects)
            if fully_in_image:
                continue

        lines = []
        for line in block["lines"]:
            dx, dy = line.get("dir", (1, 0))
            if abs(dx) < 0.5:
                continue
            text = "".join(span["text"] for span in line["spans"])
            lines.append(text)
        if lines:
            blocks.append("\n".join(lines))
    return "\n\n".join(blocks).replace("\x00", "")


BUILTIN_APPROACHES = {
    "baseline": approach_baseline,
    "dict_filter": approach_dict_filter,
    "dict_filter_images": approach_dict_filter_images,
}


def get_approach(name: str):
    if name in BUILTIN_APPROACHES:
        return BUILTIN_APPROACHES[name]
    # Load from approaches/ directory
    approach_file = APPROACHES_DIR / f"{name}.py"
    if approach_file.exists():
        ns = {}
        exec(approach_file.read_text(), ns)
        assert "extract_page" in ns, f"{approach_file} must define extract_page(page) -> str"
        return ns["extract_page"]
    available = list(BUILTIN_APPROACHES.keys())
    ext = [f.stem for f in APPROACHES_DIR.glob("*.py")]
    raise SystemExit(f"Unknown approach: {name}\n  Built-in: {available}\n  External: {ext or '(none)'}")


# ---------------------------------------------------------------------------
# Extract
# ---------------------------------------------------------------------------


def run_extract(approach_name: str):
    corpus = load_corpus()
    extract_fn = get_approach(approach_name)
    run_dir = RUNS_DIR / approach_name
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)

    total_time = 0.0
    speed_stats = {}

    for name, doc in corpus.items():
        pdf_path = resolve_pdf_path(name, doc)
        if not pdf_path.exists():
            print(f"  {name}: SKIP (file not found: {pdf_path})")
            continue

        doc_dir = run_dir / name
        doc_dir.mkdir()
        pdf = pymupdf.open(str(pdf_path))
        pages = doc.get("pages", [])

        # Quality eval pages
        t0 = time.monotonic()
        for page_idx in pages:
            if page_idx >= len(pdf):
                print(f"  {name}: page {page_idx} out of range ({len(pdf)} pages)")
                continue
            text = extract_fn(pdf[page_idx])
            (doc_dir / f"page_{page_idx:03d}.txt").write_text(text, encoding="utf-8")
        page_time = time.monotonic() - t0

        # Speed benchmark (all pages)
        if doc.get("speed_bench"):
            t0 = time.monotonic()
            for i in range(len(pdf)):
                extract_fn(pdf[i])
            full_time = time.monotonic() - t0
            speed_stats[name] = {
                "total_pages": len(pdf),
                "total_seconds": round(full_time, 3),
                "per_page_ms": round(full_time / len(pdf) * 1000, 2),
            }
            print(f"  {name}: {len(pages)} eval pages ({page_time:.2f}s) + {len(pdf)} speed bench ({full_time:.2f}s)")
        else:
            print(f"  {name}: {len(pages)} eval pages ({page_time:.2f}s)")

        total_time += page_time
        pdf.close()

    # Write meta
    meta_lines = [f'approach = "{approach_name}"', f"total_eval_seconds = {total_time:.3f}", ""]
    if speed_stats:
        for doc_name, stats in speed_stats.items():
            meta_lines.append(f"[speed.{doc_name}]")
            for k, v in stats.items():
                meta_lines.append(f"{k} = {v}")
            meta_lines.append("")
    (run_dir / "meta.toml").write_text("\n".join(meta_lines), encoding="utf-8")
    print(f"\nDone. Results in {run_dir}/")


# ---------------------------------------------------------------------------
# Compare
# ---------------------------------------------------------------------------


def run_compare(run_a: str, run_b: str, doc_filter: str | None = None):
    dir_a = RUNS_DIR / run_a
    dir_b = RUNS_DIR / run_b
    assert dir_a.exists(), f"Run not found: {dir_a}"
    assert dir_b.exists(), f"Run not found: {dir_b}"

    # Collect all doc/page pairs
    docs_a = sorted(d.name for d in dir_a.iterdir() if d.is_dir())
    docs_b = sorted(d.name for d in dir_b.iterdir() if d.is_dir())
    all_docs = sorted(set(docs_a) | set(docs_b))
    if doc_filter:
        all_docs = [d for d in all_docs if doc_filter in d]

    total_changed = 0
    total_pages = 0

    for doc_name in all_docs:
        da = dir_a / doc_name
        db = dir_b / doc_name
        if not da.exists():
            print(f"\n{'=' * 60}\n{doc_name}: only in {run_b}\n{'=' * 60}")
            continue
        if not db.exists():
            print(f"\n{'=' * 60}\n{doc_name}: only in {run_a}\n{'=' * 60}")
            continue

        pages_a = sorted(da.glob("page_*.txt"))
        pages_b = sorted(db.glob("page_*.txt"))
        page_names = sorted(set(p.name for p in pages_a) | set(p.name for p in pages_b))

        doc_changes = []
        for pname in page_names:
            fa = da / pname
            fb = db / pname
            text_a = fa.read_text(encoding="utf-8") if fa.exists() else ""
            text_b = fb.read_text(encoding="utf-8") if fb.exists() else ""
            total_pages += 1
            if text_a == text_b:
                continue
            total_changed += 1

            lines_a = text_a.splitlines(keepends=True)
            lines_b = text_b.splitlines(keepends=True)
            diff = list(
                difflib.unified_diff(lines_a, lines_b, fromfile=f"{run_a}/{pname}", tofile=f"{run_b}/{pname}", n=2)
            )
            # Summary stats
            removed = sum(1 for d in diff if d.startswith("-") and not d.startswith("---"))
            added = sum(1 for d in diff if d.startswith("+") and not d.startswith("+++"))
            len_a = len(text_a)
            len_b = len(text_b)
            doc_changes.append((pname, removed, added, len_a, len_b, diff))

        if not doc_changes:
            print(f"\n{doc_name}: identical")
            continue

        print(f"\n{'=' * 60}")
        print(f"{doc_name}: {len(doc_changes)}/{len(page_names)} pages changed")
        print(f"{'=' * 60}")
        for pname, removed, added, len_a, len_b, diff in doc_changes:
            pct = (len_b - len_a) / len_a * 100 if len_a else 0
            sign = "+" if pct >= 0 else ""
            print(f"\n  {pname}: -{removed} +{added} lines | {len_a}→{len_b} chars ({sign}{pct:.0f}%)")
            # Show first 40 diff lines
            for line in diff[:40]:
                print(f"    {line}", end="")
            if len(diff) > 40:
                print(f"    ... ({len(diff) - 40} more diff lines)")

    # Speed comparison
    meta_a = dir_a / "meta.toml"
    meta_b = dir_b / "meta.toml"
    if meta_a.exists() and meta_b.exists():
        print(f"\n{'=' * 60}")
        print("Speed comparison")
        print(f"{'=' * 60}")
        with open(meta_a, "rb") as f:
            ma = tomli.load(f)
        with open(meta_b, "rb") as f:
            mb = tomli.load(f)
        sa = ma.get("speed", {})
        sb = mb.get("speed", {})
        for doc_name in sorted(set(sa) | set(sb)):
            if doc_name in sa and doc_name in sb:
                ta = sa[doc_name]["total_seconds"]
                tb = sb[doc_name]["total_seconds"]
                ratio = tb / ta if ta else 0
                print(f"  {doc_name}: {ta:.2f}s → {tb:.2f}s ({ratio:.2f}x)")
            elif doc_name in sa:
                print(f"  {doc_name}: {sa[doc_name]['total_seconds']:.2f}s → (not in {run_b})")
            else:
                print(f"  {doc_name}: (not in {run_a}) → {sb[doc_name]['total_seconds']:.2f}s")

    print(f"\nSummary: {total_changed}/{total_pages} pages changed across {len(all_docs)} documents")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return

    cmd = args[0]

    if cmd == "fetch":
        print("Fetching remote PDFs...")
        fetch_corpus()

    elif cmd == "extract":
        assert len(args) >= 2, "Usage: run.py extract <approach_name>"
        approach = args[1]
        print(f"Extracting with approach: {approach}")
        run_extract(approach)

    elif cmd == "compare":
        assert len(args) >= 3, "Usage: run.py compare <run_a> <run_b> [--doc NAME]"
        run_a, run_b = args[1], args[2]
        doc_filter = None
        if "--doc" in args:
            doc_filter = args[args.index("--doc") + 1]
        print(f"Comparing {run_a} vs {run_b}" + (f" (filter: {doc_filter})" if doc_filter else ""))
        run_compare(run_a, run_b, doc_filter)

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)


if __name__ == "__main__":
    main()

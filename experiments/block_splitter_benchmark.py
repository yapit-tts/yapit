# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Block splitter parameter benchmark.

Runs all parameter combinations against test corpus and outputs stats + actual splits.

Usage:
    uv run scripts/block_splitter_benchmark.py
    uv run scripts/block_splitter_benchmark.py --output results.json
    uv run scripts/block_splitter_benchmark.py --verbose  # show actual splits
"""

import argparse
import json
import re
import statistics
import sys
from dataclasses import dataclass, field
from itertools import product
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from yapit.gateway.markdown.parser import parse_markdown
from yapit.gateway.markdown.transformer import transform_to_document


@dataclass
class SectionStats:
    """Stats for a single text section."""

    name: str
    block_count: int
    char_counts: list[int]
    median: float
    p95: float
    max_chars: int
    min_chars: int

    # Actual split texts for qualitative review
    splits: list[str] = field(default_factory=list)


@dataclass
class ParamStats:
    """Stats for a parameter combination across all sections."""

    max_block_chars: int
    soft_limit_mult: float
    min_chunk_size: int

    total_blocks: int = 0
    all_char_counts: list[int] = field(default_factory=list)
    section_stats: list[SectionStats] = field(default_factory=list)

    @property
    def median(self) -> float:
        return statistics.median(self.all_char_counts) if self.all_char_counts else 0

    @property
    def p95(self) -> float:
        if not self.all_char_counts:
            return 0
        sorted_counts = sorted(self.all_char_counts)
        idx = int(len(sorted_counts) * 0.95)
        return sorted_counts[min(idx, len(sorted_counts) - 1)]

    @property
    def max_chars(self) -> int:
        return max(self.all_char_counts) if self.all_char_counts else 0

    @property
    def min_chars(self) -> int:
        return min(self.all_char_counts) if self.all_char_counts else 0


def extract_sections(corpus_path: Path) -> list[tuple[str, str]]:
    """Extract named sections from test corpus.

    Returns list of (section_name, markdown_content) tuples.
    """
    content = corpus_path.read_text()

    # Split by ## headers, keeping the header with content
    sections = []
    current_name = None
    current_content = []

    for line in content.split("\n"):
        if line.startswith("## "):
            if current_name and current_content:
                sections.append((current_name, "\n".join(current_content)))
            # Extract section name (e.g., "## 1. Dense Academic Prose" -> "Dense Academic Prose")
            match = re.match(r"## \d+\.\s*(.+)", line)
            current_name = match.group(1) if match else line[3:]
            current_content = []
        elif current_name is not None:
            current_content.append(line)

    # Don't forget the last section
    if current_name and current_content:
        sections.append((current_name, "\n".join(current_content)))

    return sections


def analyze_params(
    sections: list[tuple[str, str]],
    max_block_chars: int,
    soft_limit_mult: float,
    min_chunk_size: int,
) -> ParamStats:
    """Run parameter combination on all sections and collect stats."""
    stats = ParamStats(
        max_block_chars=max_block_chars,
        soft_limit_mult=soft_limit_mult,
        min_chunk_size=min_chunk_size,
    )

    for name, content in sections:
        ast = parse_markdown(content)
        doc = transform_to_document(
            ast,
            max_block_chars=max_block_chars,
            soft_limit_mult=soft_limit_mult,
            min_chunk_size=min_chunk_size,
        )

        # Collect char counts from audio blocks only
        char_counts = []
        splits = []
        for block in doc.blocks:
            # List blocks: collect individual items (they have their own audio_block_idx)
            if hasattr(block, "items"):
                for item in block.items:
                    if item.audio_block_idx is not None and item.plain_text:
                        text = item.plain_text.strip()
                        if text:
                            char_counts.append(len(text))
                            splits.append(text)
            # Other blocks with audio
            elif hasattr(block, "audio_block_idx") and block.audio_block_idx is not None:
                if hasattr(block, "plain_text") and block.plain_text:
                    text = block.plain_text.strip()
                    if text:
                        char_counts.append(len(text))
                        splits.append(text)

        if char_counts:
            section_stat = SectionStats(
                name=name,
                block_count=len(char_counts),
                char_counts=char_counts,
                median=statistics.median(char_counts),
                p95=sorted(char_counts)[int(len(char_counts) * 0.95)] if len(char_counts) > 1 else char_counts[0],
                max_chars=max(char_counts),
                min_chars=min(char_counts),
                splits=splits,
            )
            stats.section_stats.append(section_stat)
            stats.total_blocks += len(char_counts)
            stats.all_char_counts.extend(char_counts)

    return stats


def format_summary_row(stats: ParamStats) -> str:
    """Format a single row for the summary table."""
    return (
        f"| {stats.max_block_chars:4d} | {stats.soft_limit_mult:4.1f} | {stats.min_chunk_size:3d} | "
        f"{stats.total_blocks:4d} | {stats.median:6.1f} | {stats.p95:6.1f} | {stats.max_chars:4d} | {stats.min_chars:4d} |"
    )


def print_splits(stats: ParamStats) -> None:
    """Print actual splits for qualitative review."""
    print(f"\n{'=' * 80}")
    print(f"SPLITS: max={stats.max_block_chars}, soft={stats.soft_limit_mult}, min_chunk={stats.min_chunk_size}")
    print(f"{'=' * 80}")

    for section in stats.section_stats:
        print(f"\n--- {section.name} ({section.block_count} blocks) ---")
        for i, split in enumerate(section.splits):
            # Truncate long splits for display
            display = split[:100] + "..." if len(split) > 100 else split
            display = display.replace("\n", " ")
            marker = "⚠️" if len(split) > stats.max_block_chars else "  "
            print(f"  {marker} [{len(split):3d}] {display}")


def main():
    parser = argparse.ArgumentParser(description="Block splitter parameter benchmark")
    parser.add_argument("--output", "-o", type=Path, help="Output JSON file")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show actual splits")
    parser.add_argument("--filter-max", type=int, nargs="+", help="Only test these max_block_chars values")
    parser.add_argument("--filter-soft", type=float, nargs="+", help="Only test these soft_limit_mult values")
    parser.add_argument("--filter-min", type=int, nargs="+", help="Only test these min_chunk_size values")
    args = parser.parse_args()

    corpus_path = Path(__file__).parent / "block-splitter-test-corpus.md"
    if not corpus_path.exists():
        print(f"Error: Test corpus not found at {corpus_path}", file=sys.stderr)
        sys.exit(1)

    sections = extract_sections(corpus_path)
    print(f"Loaded {len(sections)} sections from test corpus")

    # Parameter space
    max_block_chars_vals = args.filter_max or [150, 200, 250, 300]
    soft_limit_mult_vals = args.filter_soft or [1.0, 1.3, 1.7, 2.0]
    min_chunk_size_vals = args.filter_min or [20, 40, 60, 80]

    total_combos = len(max_block_chars_vals) * len(soft_limit_mult_vals) * len(min_chunk_size_vals)
    print(f"Testing {total_combos} parameter combinations\n")

    # Header
    print("| max  | soft | min | blks | median |   p95  |  max | min  |")
    print("|------|------|-----|------|--------|--------|------|------|")

    all_stats = []
    for max_chars, soft_mult, min_chunk in product(max_block_chars_vals, soft_limit_mult_vals, min_chunk_size_vals):
        stats = analyze_params(sections, max_chars, soft_mult, min_chunk)
        all_stats.append(stats)
        print(format_summary_row(stats))

        if args.verbose:
            print_splits(stats)

    # Output JSON if requested
    if args.output:
        output_data = []
        for stats in all_stats:
            output_data.append(
                {
                    "params": {
                        "max_block_chars": stats.max_block_chars,
                        "soft_limit_mult": stats.soft_limit_mult,
                        "min_chunk_size": stats.min_chunk_size,
                    },
                    "summary": {
                        "total_blocks": stats.total_blocks,
                        "median": stats.median,
                        "p95": stats.p95,
                        "max": stats.max_chars,
                        "min": stats.min_chars,
                    },
                    "sections": [
                        {
                            "name": s.name,
                            "block_count": s.block_count,
                            "median": s.median,
                            "p95": s.p95,
                            "max": s.max_chars,
                            "min": s.min_chars,
                            "splits": s.splits,
                        }
                        for s in stats.section_stats
                    ],
                }
            )

        args.output.write_text(json.dumps(output_data, indent=2))
        print(f"\nWrote detailed results to {args.output}")

    # Summary analysis
    print("\n" + "=" * 70)
    print("ANALYSIS SUMMARY")
    print("=" * 70)

    # Find configs that keep max under 350 (latency safe zone)
    safe_configs = [s for s in all_stats if s.max_chars <= 350]
    print(f"\nConfigs with max <= 350 chars (latency safe): {len(safe_configs)}/{len(all_stats)}")

    # Among safe configs, find those with highest median (less fragmentation)
    if safe_configs:
        best_median = max(safe_configs, key=lambda s: s.median)
        print(f"Best median among safe configs: {best_median.median:.1f} chars")
        print(
            f"  -> max={best_median.max_block_chars}, soft={best_median.soft_limit_mult}, min_chunk={best_median.min_chunk_size}"
        )

    # Find configs that avoid very small blocks (<30 chars) entirely
    no_tiny_configs = [s for s in all_stats if s.min_chars >= 30]
    print(f"\nConfigs with no blocks < 30 chars: {len(no_tiny_configs)}/{len(all_stats)}")


if __name__ == "__main__":
    main()

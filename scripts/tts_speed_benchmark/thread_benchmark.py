#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "kokoro>=0.9",
#     "torch",
#     "numpy",
#     "pip",
#     "phonemizer-fork",
# ]
# ///
"""Kokoro Thread Scaling Benchmark

Measures how synthesis latency scales with different OMP_NUM_THREADS settings.
Since OMP_NUM_THREADS must be set before importing torch, this script spawns
subprocesses with different thread configurations.

Usage:
    uv run scripts/tts_speed_benchmark/thread_benchmark.py

    # Test specific thread counts:
    uv run scripts/tts_speed_benchmark/thread_benchmark.py --threads 1 2 4

    # More iterations for stable measurements:
    uv run scripts/tts_speed_benchmark/thread_benchmark.py --iterations 20
"""

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# Test texts of varying lengths (short, medium, long)
TEST_TEXTS = [
    ("short", "Hello world, this is a test."),
    (
        "medium",
        "The quick brown fox jumps over the lazy dog. This sentence contains every letter of the alphabet and is commonly used for testing.",
    ),
    (
        "long",
        """In the heart of the ancient forest, where sunlight filtered through the towering canopy of oak and beech trees,
a small stream meandered its way through mossy rocks and fallen logs. The air was thick with the scent of pine and
the distant calls of songbirds echoed through the woodland. A fox emerged from the underbrush, its russet coat
gleaming in the dappled light, pausing to drink from the crystal-clear water before continuing on its silent journey
through the timeless realm of nature.""",
    ),
]

SAMPLE_RATE = 24000
BYTES_PER_SAMPLE = 2


@dataclass
class BenchmarkResult:
    threads: int
    text_type: str
    char_count: int
    iterations: int
    latencies_ms: list[float]
    audio_duration_ms: float

    @property
    def mean_latency_ms(self) -> float:
        return sum(self.latencies_ms) / len(self.latencies_ms)

    @property
    def min_latency_ms(self) -> float:
        return min(self.latencies_ms)

    @property
    def max_latency_ms(self) -> float:
        return max(self.latencies_ms)

    @property
    def real_time_factor(self) -> float:
        """RTF = audio_duration / synthesis_time. >1 means faster than real-time."""
        return self.audio_duration_ms / self.mean_latency_ms if self.mean_latency_ms > 0 else 0


def run_worker(threads: int, text: str, iterations: int) -> tuple[list[float], float]:
    """Run synthesis in a subprocess with specific thread count.

    Returns (latencies_ms, audio_duration_ms).
    """
    worker_code = '''
import os
os.environ["OMP_NUM_THREADS"] = "{threads}"
os.environ["MKL_NUM_THREADS"] = "{threads}"
os.environ["OPENBLAS_NUM_THREADS"] = "{threads}"

import json
import sys
import time
import numpy as np

# Now import torch (after env vars set)
import torch
torch.set_num_threads({threads})

from kokoro import KPipeline

# Load model
pipe = KPipeline(repo_id="hexgrad/Kokoro-82M", lang_code="a", device="cpu")

text = """{text}"""
iterations = {iterations}

# Warm-up run (first inference is slow)
for _, _, audio in pipe(text, voice="af_heart", speed=1.0):
    pass

latencies = []
audio_bytes_len = 0

for i in range(iterations):
    start = time.perf_counter()
    audio_bytes = b"".join(
        (audio.numpy() * 32767).astype(np.int16).tobytes()
        for _, _, audio in pipe(text, voice="af_heart", speed=1.0)
        if audio is not None
    )
    elapsed_ms = (time.perf_counter() - start) * 1000
    latencies.append(elapsed_ms)
    audio_bytes_len = len(audio_bytes)

# Calculate audio duration (24kHz, mono, 16-bit)
audio_duration_ms = audio_bytes_len / (24000 * 1 * 2) * 1000

print(json.dumps({{"latencies": latencies, "audio_duration_ms": audio_duration_ms}}))
'''

    # Escape the text for embedding in code
    escaped_text = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    code = worker_code.format(threads=threads, text=escaped_text, iterations=iterations)

    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=300,
    )

    if result.returncode != 0:
        print(f"Worker failed: {result.stderr}", file=sys.stderr)
        raise RuntimeError(f"Worker failed with code {result.returncode}")

    data = json.loads(result.stdout.strip())
    return data["latencies"], data["audio_duration_ms"]


def run_benchmark(thread_counts: list[int], iterations: int) -> list[BenchmarkResult]:
    """Run benchmark for all thread counts and text types."""
    results = []

    for threads in thread_counts:
        print(f"\n{'=' * 60}")
        print(f"Testing OMP_NUM_THREADS={threads}")
        print("=" * 60)

        for text_type, text in TEST_TEXTS:
            print(f"  {text_type} ({len(text)} chars)...", end=" ", flush=True)

            try:
                latencies, audio_duration_ms = run_worker(threads, text, iterations)
                result = BenchmarkResult(
                    threads=threads,
                    text_type=text_type,
                    char_count=len(text),
                    iterations=iterations,
                    latencies_ms=latencies,
                    audio_duration_ms=audio_duration_ms,
                )
                results.append(result)
                print(f"mean={result.mean_latency_ms:.0f}ms, RTF={result.real_time_factor:.2f}x")
            except Exception as e:
                print(f"FAILED: {e}")

    return results


def print_summary(results: list[BenchmarkResult]):
    """Print summary table."""
    print("\n" + "=" * 80)
    print("SUMMARY: Mean Latency (ms) and Real-Time Factor by Thread Count")
    print("=" * 80)

    # Group by text type
    text_types = list(dict.fromkeys(r.text_type for r in results))
    thread_counts = list(dict.fromkeys(r.threads for r in results))

    # Header
    header = f"{'Text Type':<12} | " + " | ".join(f"T={t:2d}" for t in thread_counts)
    print(header)
    print("-" * len(header))

    for text_type in text_types:
        row_parts = [f"{text_type:<12}"]
        for threads in thread_counts:
            matching = [r for r in results if r.text_type == text_type and r.threads == threads]
            if matching:
                r = matching[0]
                row_parts.append(f"{r.mean_latency_ms:6.0f}ms ({r.real_time_factor:.1f}x)")
            else:
                row_parts.append("    N/A    ")
        print(" | ".join(row_parts))

    # Relative speedups
    print("\n" + "=" * 80)
    print("RELATIVE SPEEDUP vs T=1 (lower latency is better)")
    print("=" * 80)

    baseline_results = {r.text_type: r for r in results if r.threads == 1}

    for text_type in text_types:
        if text_type not in baseline_results:
            continue
        baseline = baseline_results[text_type]
        row_parts = [f"{text_type:<12}"]
        for threads in thread_counts:
            matching = [r for r in results if r.text_type == text_type and r.threads == threads]
            if matching:
                r = matching[0]
                speedup = baseline.mean_latency_ms / r.mean_latency_ms
                row_parts.append(f"   {speedup:.2f}x   ")
            else:
                row_parts.append("    N/A    ")
        print(" | ".join(row_parts))


def save_results(results: list[BenchmarkResult], output_path: Path):
    """Save results to JSON."""
    data = {
        "benchmark_type": "thread_scaling",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "results": [
            {
                "threads": r.threads,
                "text_type": r.text_type,
                "char_count": r.char_count,
                "iterations": r.iterations,
                "mean_latency_ms": r.mean_latency_ms,
                "min_latency_ms": r.min_latency_ms,
                "max_latency_ms": r.max_latency_ms,
                "audio_duration_ms": r.audio_duration_ms,
                "real_time_factor": r.real_time_factor,
                "all_latencies_ms": r.latencies_ms,
            }
            for r in results
        ],
    }
    output_path.write_text(json.dumps(data, indent=2))
    print(f"\nResults saved to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Kokoro Thread Scaling Benchmark")
    parser.add_argument(
        "--threads",
        type=int,
        nargs="+",
        default=[1, 2, 4, 8],
        help="Thread counts to test (default: 1 2 4 8)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=10,
        help="Iterations per configuration (default: 10)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output JSON file path",
    )

    args = parser.parse_args()

    print("Kokoro Thread Scaling Benchmark")
    print(f"Thread counts: {args.threads}")
    print(f"Iterations per config: {args.iterations}")
    print(f"Test texts: {[t[0] for t in TEST_TEXTS]}")

    results = run_benchmark(args.threads, args.iterations)
    print_summary(results)

    if args.output:
        save_results(results, args.output)
    else:
        output_dir = Path(__file__).parent / "results"
        output_dir.mkdir(exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"thread_benchmark_{timestamp}.json"
        save_results(results, output_path)


if __name__ == "__main__":
    main()

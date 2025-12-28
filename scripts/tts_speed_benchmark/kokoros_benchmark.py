#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "httpx",
# ]
# ///
"""Rust Kokoros Instance Scaling Benchmark

Measures how throughput scales with different --instances settings for the
Rust Kokoros TTS server.

Prerequisites:
    1. Clone and build Kokoros:
       git clone https://github.com/lucasjinreal/Kokoros
       cd Kokoros
       bash download_all.sh  # downloads model and voices
       cargo build --release

    2. Set KOKOROS_DIR to point to the built directory:
       export KOKOROS_DIR=/path/to/Kokoros

Usage:
    uv run scripts/tts_speed_benchmark/kokoros_benchmark.py

    # Test specific instance counts:
    uv run scripts/tts_speed_benchmark/kokoros_benchmark.py --instances 1 2 4

    # Skip server management (if already running):
    uv run scripts/tts_speed_benchmark/kokoros_benchmark.py --url http://localhost:3000
"""

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

# Same test texts as thread benchmark for comparison
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
through the timeless realm of nature.""".replace("\n", " "),
    ),
]

DEFAULT_VOICE = "af_sky"


@dataclass
class BenchmarkResult:
    instances: int
    text_type: str
    char_count: int
    iterations: int
    latencies_ms: list[float]
    audio_duration_ms: float

    @property
    def mean_latency_ms(self) -> float:
        return sum(self.latencies_ms) / len(self.latencies_ms) if self.latencies_ms else 0

    @property
    def min_latency_ms(self) -> float:
        return min(self.latencies_ms) if self.latencies_ms else 0

    @property
    def max_latency_ms(self) -> float:
        return max(self.latencies_ms) if self.latencies_ms else 0

    @property
    def real_time_factor(self) -> float:
        """RTF = audio_duration / synthesis_time. >1 means faster than real-time."""
        return self.audio_duration_ms / self.mean_latency_ms if self.mean_latency_ms > 0 else 0


class KokorosServer:
    """Manages Kokoros server process."""

    def __init__(self, kokoros_dir: Path, instances: int, port: int = 3000):
        self.kokoros_dir = kokoros_dir
        self.instances = instances
        self.port = port
        self.process: subprocess.Popen | None = None
        self.url = f"http://localhost:{port}"

    def start(self) -> bool:
        """Start the Kokoros server. Returns True if started successfully."""
        binary = self.kokoros_dir / "target" / "release" / "koko"
        if not binary.exists():
            print(f"Error: Kokoros binary not found at {binary}")
            print("Run: cargo build --release in the Kokoros directory")
            return False

        cmd = [
            str(binary),
            "openai",
            "--instances",
            str(self.instances),
            "--port",
            str(self.port),
        ]

        print(f"Starting Kokoros server with {self.instances} instances on port {self.port}...")

        self.process = subprocess.Popen(
            cmd,
            cwd=self.kokoros_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Wait for server to be ready
        for attempt in range(30):
            time.sleep(1)
            try:
                with httpx.Client(timeout=5.0) as client:
                    # Try the models endpoint to check if server is up
                    resp = client.get(f"{self.url}/v1/models")
                    if resp.status_code == 200:
                        print(f"Server ready after {attempt + 1}s")
                        return True
            except Exception:
                pass

            # Check if process died
            if self.process.poll() is not None:
                stderr = self.process.stderr.read().decode() if self.process.stderr else ""
                print(f"Server process died: {stderr}")
                return False

        print("Server failed to start within 30 seconds")
        self.stop()
        return False

    def stop(self):
        """Stop the server."""
        if self.process:
            print("Stopping Kokoros server...")
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None


def synthesize(url: str, text: str, voice: str = DEFAULT_VOICE) -> tuple[float, float]:
    """Synthesize text via Kokoros OpenAI-compatible API.

    Returns (latency_ms, audio_duration_ms).
    """
    payload = {
        "model": "kokoro",
        "input": text,
        "voice": voice,
        "response_format": "pcm",  # Raw PCM for accurate duration calculation
    }

    start = time.perf_counter()
    with httpx.Client(timeout=120.0) as client:
        response = client.post(
            f"{url}/v1/audio/speech",
            json=payload,
        )
        response.raise_for_status()
    latency_ms = (time.perf_counter() - start) * 1000

    # Calculate audio duration from PCM data
    # Kokoros outputs 24kHz mono 16-bit PCM
    audio_bytes = response.content
    audio_duration_ms = len(audio_bytes) / (24000 * 2) * 1000

    return latency_ms, audio_duration_ms


def run_benchmark_for_instances(
    url: str,
    instances: int,
    iterations: int,
) -> list[BenchmarkResult]:
    """Run benchmark for a specific instance count."""
    results = []

    for text_type, text in TEST_TEXTS:
        print(f"  {text_type} ({len(text)} chars)...", end=" ", flush=True)

        latencies = []
        audio_duration_ms = 0

        # Warm-up run
        try:
            synthesize(url, text)
        except Exception as e:
            print(f"FAILED (warmup): {e}")
            continue

        for _ in range(iterations):
            try:
                latency, duration = synthesize(url, text)
                latencies.append(latency)
                audio_duration_ms = duration
            except Exception as e:
                print(f"FAILED: {e}")
                break

        if latencies:
            result = BenchmarkResult(
                instances=instances,
                text_type=text_type,
                char_count=len(text),
                iterations=len(latencies),
                latencies_ms=latencies,
                audio_duration_ms=audio_duration_ms,
            )
            results.append(result)
            print(f"mean={result.mean_latency_ms:.0f}ms, RTF={result.real_time_factor:.2f}x")

    return results


def run_benchmark(
    kokoros_dir: Path | None,
    base_url: str | None,
    instance_counts: list[int],
    iterations: int,
) -> list[BenchmarkResult]:
    """Run full benchmark, managing server if needed."""
    all_results = []

    if base_url:
        # External server mode - just run benchmark
        print(f"Using existing server at {base_url}")
        # Assume single instance count from external server
        all_results.extend(
            run_benchmark_for_instances(
                base_url,
                instances=0,  # Unknown
                iterations=iterations,
            )
        )
    else:
        # Managed server mode
        if not kokoros_dir:
            print("Error: Must specify either --kokoros-dir or --url")
            sys.exit(1)

        for instances in instance_counts:
            print(f"\n{'=' * 60}")
            print(f"Testing --instances={instances}")
            print("=" * 60)

            server = KokorosServer(kokoros_dir, instances)
            if not server.start():
                print(f"Skipping instances={instances} due to server failure")
                continue

            try:
                results = run_benchmark_for_instances(
                    server.url,
                    instances,
                    iterations,
                )
                all_results.extend(results)
            finally:
                server.stop()

    return all_results


def print_summary(results: list[BenchmarkResult]):
    """Print summary table."""
    print("\n" + "=" * 80)
    print("SUMMARY: Mean Latency (ms) and Real-Time Factor by Instance Count")
    print("=" * 80)

    text_types = list(dict.fromkeys(r.text_type for r in results))
    instance_counts = sorted(set(r.instances for r in results))

    # Header
    header = f"{'Text Type':<12} | " + " | ".join(f"I={i:2d}" for i in instance_counts)
    print(header)
    print("-" * len(header))

    for text_type in text_types:
        row_parts = [f"{text_type:<12}"]
        for instances in instance_counts:
            matching = [r for r in results if r.text_type == text_type and r.instances == instances]
            if matching:
                r = matching[0]
                row_parts.append(f"{r.mean_latency_ms:6.0f}ms ({r.real_time_factor:.1f}x)")
            else:
                row_parts.append("    N/A    ")
        print(" | ".join(row_parts))

    # Relative comparison if we have baseline
    if 1 in instance_counts:
        print("\n" + "=" * 80)
        print("RELATIVE SPEEDUP vs I=1 (lower latency is better)")
        print("=" * 80)

        baseline_results = {r.text_type: r for r in results if r.instances == 1}

        for text_type in text_types:
            if text_type not in baseline_results:
                continue
            baseline = baseline_results[text_type]
            row_parts = [f"{text_type:<12}"]
            for instances in instance_counts:
                matching = [r for r in results if r.text_type == text_type and r.instances == instances]
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
        "benchmark_type": "kokoros_instance_scaling",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "results": [
            {
                "instances": r.instances,
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
    parser = argparse.ArgumentParser(description="Kokoros Instance Scaling Benchmark")
    parser.add_argument(
        "--kokoros-dir",
        type=Path,
        default=os.environ.get("KOKOROS_DIR"),
        help="Path to Kokoros repo (or set KOKOROS_DIR env var)",
    )
    parser.add_argument(
        "--url",
        help="Use existing server URL instead of managing server",
    )
    parser.add_argument(
        "--instances",
        type=int,
        nargs="+",
        default=[1, 2, 4],
        help="Instance counts to test (default: 1 2 4)",
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

    print("Kokoros Instance Scaling Benchmark")
    if args.url:
        print(f"Using external server: {args.url}")
    else:
        if not args.kokoros_dir:
            print("Error: Must specify --kokoros-dir or set KOKOROS_DIR environment variable")
            print("\nSetup instructions:")
            print("  git clone https://github.com/lucasjinreal/Kokoros")
            print("  cd Kokoros")
            print("  bash download_all.sh")
            print("  cargo build --release")
            print("  export KOKOROS_DIR=$(pwd)")
            sys.exit(1)
        print(f"Kokoros dir: {args.kokoros_dir}")
        print(f"Instance counts: {args.instances}")

    print(f"Iterations per config: {args.iterations}")
    print(f"Test texts: {[t[0] for t in TEST_TEXTS]}")

    results = run_benchmark(
        args.kokoros_dir,
        args.url,
        args.instances,
        args.iterations,
    )

    if results:
        print_summary(results)

        if args.output:
            save_results(results, args.output)
        else:
            output_dir = Path(__file__).parent / "results"
            output_dir.mkdir(exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            output_path = output_dir / f"kokoros_benchmark_{timestamp}.json"
            save_results(results, output_path)
    else:
        print("\nNo results collected - check for errors above")


if __name__ == "__main__":
    main()

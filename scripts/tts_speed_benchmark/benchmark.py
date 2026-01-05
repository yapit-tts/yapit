#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "httpx",
#     "rich",
#     "kokoro>=0.9",
#     "torch",
#     "numpy",
#     "pip",
#     "phonemizer-fork",
# ]
# ///
"""TTS Speed Benchmark Script

Measures chars-per-second for TTS models by synthesizing test corpus samples
and analyzing the relationship between input text length and output audio duration.

Usage:
    # Kokoro directly (recommended):
    uv run scripts/tts_speed_benchmark/benchmark.py --kokoro

    # With specific voice:
    uv run scripts/tts_speed_benchmark/benchmark.py --kokoro --voice af_heart

    # Kokoro via HTTP endpoint (if running as service):
    uv run scripts/tts_speed_benchmark/benchmark.py --url http://localhost:8001

    # HIGGS via RunPod (requires RUNPOD_API_KEY):
    uv run scripts/tts_speed_benchmark/benchmark.py --runpod-endpoint u3n08ucrd64b3p
"""

import argparse
import base64
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import numpy as np
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.table import Table

# Add parent to path for corpus import
sys.path.insert(0, str(Path(__file__).parent))
from corpus import get_all_samples

console = Console()

# Lazy-loaded Kokoro pipeline
_kokoro_pipe = None


@dataclass
class SynthesisResult:
    sample_id: str
    category: str
    text: str
    char_count: int
    duration_ms: int
    synthesis_time_ms: float
    chars_per_second: float
    success: bool
    error: str | None = None


@dataclass
class BenchmarkResults:
    model: str
    voice: str
    results: list[SynthesisResult] = field(default_factory=list)

    @property
    def successful_results(self) -> list[SynthesisResult]:
        return [r for r in self.results if r.success]

    @property
    def failed_results(self) -> list[SynthesisResult]:
        return [r for r in self.results if not r.success]

    def stats(self) -> dict:
        if not self.successful_results:
            return {}

        cps_values = [r.chars_per_second for r in self.successful_results]
        return {
            "count": len(self.successful_results),
            "failed": len(self.failed_results),
            "mean_cps": statistics.mean(cps_values),
            "median_cps": statistics.median(cps_values),
            "stdev_cps": statistics.stdev(cps_values) if len(cps_values) > 1 else 0,
            "min_cps": min(cps_values),
            "max_cps": max(cps_values),
            "total_chars": sum(r.char_count for r in self.successful_results),
            "total_duration_ms": sum(r.duration_ms for r in self.successful_results),
            "total_synthesis_time_ms": sum(r.synthesis_time_ms for r in self.successful_results),
        }

    def stats_by_category(self) -> dict[str, dict]:
        from collections import defaultdict

        by_cat = defaultdict(list)
        for r in self.successful_results:
            by_cat[r.category].append(r)

        result = {}
        for cat, results in by_cat.items():
            cps_values = [r.chars_per_second for r in results]
            result[cat] = {
                "count": len(results),
                "mean_cps": statistics.mean(cps_values),
                "stdev_cps": statistics.stdev(cps_values) if len(cps_values) > 1 else 0,
            }
        return result


def get_kokoro_pipe():
    """Lazy-load Kokoro pipeline."""
    global _kokoro_pipe
    if _kokoro_pipe is None:
        from kokoro import KPipeline

        console.print("[yellow]Loading Kokoro model...[/yellow]")
        _kokoro_pipe = KPipeline(repo_id="hexgrad/Kokoro-82M", lang_code="a", device="cpu")
    return _kokoro_pipe


def synthesize_kokoro(text: str, voice: str = "af_heart", speed: float = 1.0) -> tuple[int, float]:
    """Synthesize text directly with Kokoro.
    Returns (duration_ms, synthesis_time_ms).
    """
    pipe = get_kokoro_pipe()

    start = time.perf_counter()
    audio_bytes = b"".join(
        (audio.numpy() * 32767).astype(np.int16).tobytes()
        for _, _, audio in pipe(text, voice=voice, speed=speed)
        if audio is not None
    )
    elapsed_ms = (time.perf_counter() - start) * 1000

    # 24kHz, mono, 16-bit
    duration_ms = int(len(audio_bytes) / (24_000 * 1 * 2) * 1000)
    return duration_ms, elapsed_ms


def synthesize_local(
    url: str,
    text: str,
    model_slug: str = "kokoro-cpu",
    voice_slug: str = "af_heart",
    codec: str = "pcm",
) -> tuple[int, float]:
    """Synthesize text via local worker endpoint.
    Returns (duration_ms, synthesis_time_ms).
    """
    payload = {
        "model_slug": model_slug,
        "voice_slug": voice_slug,
        "text": text,
        "codec": codec,
        "kwargs": {"voice": voice_slug},
    }

    start = time.perf_counter()
    with httpx.Client(timeout=120.0) as client:
        response = client.post(f"{url}/synthesize", json=payload)
        response.raise_for_status()
    elapsed_ms = (time.perf_counter() - start) * 1000

    data = response.json()
    return data["duration_ms"], elapsed_ms


def load_voice_prompt(voice_slug: str) -> tuple[str, str]:
    """Load voice prompt files for HIGGS.
    Returns (base64_audio, transcript).
    """
    # Voice prompts are in yapit/data/voice_prompts/
    # Map slug to filename: "en-woman" -> "en_woman"
    filename = voice_slug.replace("-", "_")
    voice_dir = Path(__file__).parent.parent.parent / "yapit/data/voice_prompts"
    audio_path = voice_dir / f"{filename}.wav"
    transcript_path = voice_dir / f"{filename}.txt"

    if not audio_path.exists():
        raise FileNotFoundError(f"Voice prompt not found: {audio_path}")

    audio_b64 = base64.b64encode(audio_path.read_bytes()).decode("utf-8")
    transcript = transcript_path.read_text(encoding="utf-8").strip()
    return audio_b64, transcript


# Cache loaded voice prompts
_voice_prompt_cache: dict[str, tuple[str, str]] = {}


def get_voice_prompt(voice_slug: str) -> tuple[str, str]:
    """Get cached voice prompt."""
    if voice_slug not in _voice_prompt_cache:
        _voice_prompt_cache[voice_slug] = load_voice_prompt(voice_slug)
    return _voice_prompt_cache[voice_slug]


def synthesize_runpod(
    endpoint_id: str,
    text: str,
    voice_slug: str = "en-woman",
    api_key: str | None = None,
) -> tuple[int, float]:
    """Synthesize text via RunPod serverless endpoint (HIGGS).
    Returns (duration_ms, synthesis_time_ms).
    """
    api_key = api_key or os.environ.get("RUNPOD_API_KEY")
    if not api_key:
        raise ValueError("RUNPOD_API_KEY not set")

    # Load voice prompt for HIGGS
    ref_audio, ref_transcript = get_voice_prompt(voice_slug)

    url = f"https://api.runpod.ai/v2/{endpoint_id}/runsync"
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {
        "input": {
            "text": text,
            "kwargs": {
                "ref_audio": ref_audio,
                "ref_audio_transcript": ref_transcript,
                "seed": 42,
                "temperature": 0.3,
            },
        }
    }

    start = time.perf_counter()
    with httpx.Client(timeout=300.0) as client:
        response = client.post(url, json=payload, headers=headers)
        response.raise_for_status()
    elapsed_ms = (time.perf_counter() - start) * 1000

    data = response.json()
    if data.get("status") != "COMPLETED":
        raise RuntimeError(f"RunPod job failed: {data}")

    output = data.get("output", {})
    return output.get("duration_ms", 0), elapsed_ms


def run_benchmark(
    synthesize_fn,
    model: str,
    voice: str,
    samples: list[tuple[str, str, str]] | None = None,
    limit: int | None = None,
) -> BenchmarkResults:
    """Run benchmark on all samples."""
    if samples is None:
        samples = get_all_samples()

    if limit:
        samples = samples[:limit]

    results = BenchmarkResults(model=model, voice=voice)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(f"Benchmarking {model}/{voice}...", total=len(samples))

        for category, sample_id, text in samples:
            char_count = len(text)

            try:
                duration_ms, synthesis_time_ms = synthesize_fn(text)
                duration_sec = duration_ms / 1000
                cps = char_count / duration_sec if duration_sec > 0 else 0

                results.results.append(
                    SynthesisResult(
                        sample_id=sample_id,
                        category=category,
                        text=text[:100] + "..." if len(text) > 100 else text,
                        char_count=char_count,
                        duration_ms=duration_ms,
                        synthesis_time_ms=synthesis_time_ms,
                        chars_per_second=cps,
                        success=True,
                    )
                )
            except Exception as e:
                results.results.append(
                    SynthesisResult(
                        sample_id=sample_id,
                        category=category,
                        text=text[:100] + "..." if len(text) > 100 else text,
                        char_count=char_count,
                        duration_ms=0,
                        synthesis_time_ms=0,
                        chars_per_second=0,
                        success=False,
                        error=str(e),
                    )
                )

            progress.update(task, advance=1)

    return results


def print_results(results: BenchmarkResults):
    """Print benchmark results as tables."""
    stats = results.stats()
    if not stats:
        console.print("[red]No successful results![/red]")
        return

    # Overall stats
    console.print(f"\n[bold]Overall Statistics for {results.model}/{results.voice}[/bold]")
    table = Table()
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Samples processed", str(stats["count"]))
    table.add_row("Failed samples", str(stats["failed"]))
    table.add_row("Mean CPS", f"{stats['mean_cps']:.2f}")
    table.add_row("Median CPS", f"{stats['median_cps']:.2f}")
    table.add_row("Std Dev", f"{stats['stdev_cps']:.2f}")
    table.add_row("Min CPS", f"{stats['min_cps']:.2f}")
    table.add_row("Max CPS", f"{stats['max_cps']:.2f}")
    table.add_row("Total characters", str(stats["total_chars"]))
    table.add_row("Total audio duration", f"{stats['total_duration_ms'] / 1000:.1f}s")
    table.add_row("Total synthesis time", f"{stats['total_synthesis_time_ms'] / 1000:.1f}s")

    console.print(table)

    # Per-category stats
    console.print("\n[bold]Per-Category Statistics[/bold]")
    cat_table = Table()
    cat_table.add_column("Category", style="cyan")
    cat_table.add_column("Count", style="white")
    cat_table.add_column("Mean CPS", style="green")
    cat_table.add_column("Std Dev", style="yellow")

    for cat, cat_stats in sorted(results.stats_by_category().items()):
        cat_table.add_row(
            cat,
            str(cat_stats["count"]),
            f"{cat_stats['mean_cps']:.2f}",
            f"{cat_stats['stdev_cps']:.2f}",
        )

    console.print(cat_table)

    # Failed samples
    if results.failed_results:
        console.print(f"\n[bold red]Failed Samples ({len(results.failed_results)})[/bold red]")
        for r in results.failed_results:
            console.print(f"  - {r.sample_id}: {r.error}")

    # Recommendation
    console.print("\n[bold]Recommendation[/bold]")
    console.print(f"  est_chars_per_second = {stats['median_cps']:.1f}")
    console.print(f"  (±{stats['stdev_cps'] / stats['median_cps'] * 100:.0f}% variance)")


def save_results(results: BenchmarkResults, output_path: Path):
    """Save results to JSON file."""
    data = {
        "model": results.model,
        "voice": results.voice,
        "stats": results.stats(),
        "by_category": results.stats_by_category(),
        "samples": [
            {
                "sample_id": r.sample_id,
                "category": r.category,
                "char_count": r.char_count,
                "duration_ms": r.duration_ms,
                "synthesis_time_ms": r.synthesis_time_ms,
                "chars_per_second": r.chars_per_second,
                "success": r.success,
                "error": r.error,
            }
            for r in results.results
        ],
    }

    output_path.write_text(json.dumps(data, indent=2))
    console.print(f"\nResults saved to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="TTS Speed Benchmark")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--kokoro", action="store_true", help="Use Kokoro directly (no server needed)")
    group.add_argument("--url", help="Local worker URL (e.g., http://localhost:8001)")
    group.add_argument("--runpod-endpoint", help="RunPod endpoint ID for HIGGS")
    parser.add_argument("--voice", default="af_heart", help="Voice to use (default: af_heart)")
    parser.add_argument("--model", default="kokoro-cpu", help="Model slug (default: kokoro-cpu)")
    parser.add_argument("--limit", type=int, help="Limit number of samples (for testing)")
    parser.add_argument("--output", type=Path, help="Output JSON file path")

    args = parser.parse_args()

    if args.kokoro:
        # Direct Kokoro synthesis
        console.print(f"[bold]Testing Kokoro directly with voice: {args.voice}[/bold]")

        def synth_fn(text: str) -> tuple[int, float]:
            return synthesize_kokoro(text, voice=args.voice)

        results = run_benchmark(synth_fn, "kokoro", args.voice, limit=args.limit)

    elif args.url:
        # Local/Docker endpoint
        console.print(f"[bold]Testing local endpoint: {args.url}[/bold]")

        # Health check
        try:
            with httpx.Client(timeout=10.0) as client:
                health = client.get(f"{args.url}/health")
                health.raise_for_status()
                console.print("[green]Health check passed[/green]")
        except Exception as e:
            console.print(f"[red]Health check failed: {e}[/red]")
            sys.exit(1)

        def synth_fn(text: str) -> tuple[int, float]:
            return synthesize_local(
                args.url,
                text,
                model_slug=args.model,
                voice_slug=args.voice,
            )

        results = run_benchmark(synth_fn, args.model, args.voice, limit=args.limit)

    else:
        # RunPod endpoint
        console.print(f"[bold]Testing RunPod endpoint: {args.runpod_endpoint}[/bold]")

        def synth_fn(text: str) -> tuple[int, float]:
            return synthesize_runpod(
                args.runpod_endpoint,
                text,
                voice_slug=args.voice,
            )

        results = run_benchmark(synth_fn, "higgs", args.voice, limit=args.limit)

    print_results(results)

    if args.output:
        save_results(results, args.output)
    else:
        # Default output path
        output_dir = Path(__file__).parent / "results"
        output_dir.mkdir(exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"benchmark_{results.model}_{results.voice}_{timestamp}.json"
        save_results(results, output_path)


if __name__ == "__main__":
    main()

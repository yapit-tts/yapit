#!/usr/bin/env uv run
# /// script
# dependencies = ["httpx", "python-dotenv"]
# ///
"""Benchmark Inworld TTS speaking rate (chars/sec).

Results from 2026-01-21 (TTS-1.5-Mini, 8 voices, ~3500 chars):
  Mean: 14.19 chars/sec
  Range: 11.21 (Blake) - 15.71 (Sarah)
  Most voices cluster 13.5-15.7 chars/sec

Usage:
  uv run experiments/benchmark_inworld_speaking_rate.py [--voices Ashley,Craig,...]
"""

import asyncio
import base64
import json
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

INWORLD_API_BASE = "https://api.inworld.ai/tts/v1"
MODEL_ID = "inworld-tts-1.5-mini"
DEFAULT_VOICES = ["Ashley", "Craig", "Elizabeth", "Mark", "Olivia", "Dennis", "Sarah", "Blake"]

# PCM config for easy duration calculation
SAMPLE_RATE = 48000
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit = 2 bytes


async def synthesize(
    client: httpx.AsyncClient,
    api_key: str,
    model_id: str,
    voice_id: str,
    text: str,
) -> tuple[bytes, float, float]:
    """Synthesize text and return (audio_bytes, ttfb_ms, total_ms)."""
    payload = {
        "text": text,
        "voiceId": voice_id,
        "modelId": model_id,
        "audio_config": {
            "audio_encoding": "LINEAR16",
            "sample_rate_hertz": SAMPLE_RATE,
        },
    }

    audio_chunks: list[bytes] = []
    ttfb_ms = 0.0
    start = time.perf_counter()
    first_chunk = False

    async with client.stream(
        "POST",
        f"{INWORLD_API_BASE}/voice:stream",
        json=payload,
        headers={"Authorization": f"Basic {api_key}"},
    ) as response:
        if response.status_code != 200:
            await response.aread()
            raise Exception(f"HTTP {response.status_code}: {response.text[:500]}")
        async for line in response.aiter_lines():
            if not line.strip():
                continue
            if not first_chunk:
                ttfb_ms = (time.perf_counter() - start) * 1000
                first_chunk = True
            try:
                data = json.loads(line)
                audio_b64 = data.get("result", {}).get("audioContent", "")
                if audio_b64:
                    audio_chunks.append(base64.b64decode(audio_b64))
            except json.JSONDecodeError:
                pass

    total_ms = (time.perf_counter() - start) * 1000
    return b"".join(audio_chunks), ttfb_ms, total_ms


def pcm_duration(audio_bytes: bytes) -> float:
    """Calculate PCM audio duration in seconds."""
    return len(audio_bytes) / (SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH)


MAX_CHARS = 1800  # API limit is 2000, leave some margin


def load_corpus() -> list[str]:
    """Load test corpus as chunks under API limit."""
    corpus_path = Path(__file__).parent / "block-splitter-test-corpus.md"
    if corpus_path.exists():
        content = corpus_path.read_text()
        # Strip markdown formatting, keep text
        lines = []
        for line in content.split("\n"):
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("```") and line != "---":
                lines.append(line)
        full_text = " ".join(lines)
    else:
        full_text = "The quick brown fox jumps over the lazy dog. " * 50

    # Split into chunks respecting word boundaries
    chunks = []
    while full_text:
        if len(full_text) <= MAX_CHARS:
            chunks.append(full_text)
            break
        # Find last space before limit
        split_idx = full_text.rfind(" ", 0, MAX_CHARS)
        if split_idx == -1:
            split_idx = MAX_CHARS
        chunks.append(full_text[:split_idx])
        full_text = full_text[split_idx:].lstrip()
    return chunks


async def run_benchmark(api_key: str, voices: list[str]) -> None:
    """Run benchmark."""
    chunks = load_corpus()[:2]  # 2 chunks to balance coverage vs credits
    total_chars = sum(len(c) for c in chunks)
    print(f"Testing {len(voices)} voices with {total_chars} chars ({len(chunks)} chunks)\n")

    results = []
    async with httpx.AsyncClient(timeout=300.0) as client:
        for voice in voices:
            try:
                total_audio = b""
                for i, chunk in enumerate(chunks):
                    print(f"\r  {voice}: chunk {i + 1}/{len(chunks)}...", end="", flush=True)
                    audio_bytes, _, _ = await synthesize(client, api_key, MODEL_ID, voice, chunk)
                    total_audio += audio_bytes

                duration = pcm_duration(total_audio)
                chars_per_sec = total_chars / duration if duration > 0 else 0
                results.append((voice, chars_per_sec, duration))
                print(f"\r  {voice}: {chars_per_sec:.2f} chars/sec ({duration:.1f}s audio)")

            except Exception as e:
                print(f"\r  {voice}: ERROR {e}")

    if results:
        print("\n" + "=" * 40)
        print("Summary:")
        print("=" * 40)
        rates = [r[1] for r in results]
        for voice, cps, _ in sorted(results, key=lambda x: -x[1]):
            print(f"  {voice:12s}: {cps:.2f} chars/sec")
        print(f"\n  Mean: {sum(rates) / len(rates):.2f} chars/sec")
        print(f"  Min:  {min(rates):.2f} | Max: {max(rates):.2f}")


async def main():
    env_path = Path(__file__).parent.parent / ".env"
    load_dotenv(env_path)
    api_key = os.getenv("INWORLD_API_KEY")
    if not api_key:
        print("ERROR: INWORLD_API_KEY not found in .env")
        sys.exit(1)

    # Parse --voices arg
    voices = DEFAULT_VOICES
    for arg in sys.argv[1:]:
        if arg.startswith("--voices="):
            voices = arg.split("=", 1)[1].split(",")

    print("Inworld TTS 1.5 Speaking Rate Benchmark")
    print(f"Model: {MODEL_ID}")
    await run_benchmark(api_key, voices)


if __name__ == "__main__":
    asyncio.run(main())

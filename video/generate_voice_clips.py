# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx", "python-dotenv", "tyro"]
# ///
"""Generate InWorld voice clips for the Remotion trailer.

Two sets:
  narration/  — English voices narrating over the product demo
  showcase/   — Multilingual voice showcase (one voice per language)

Edit the lists below to change lines. Re-run to regenerate.

Usage:
    uv run scripts/generate_voice_clips.py
    uv run scripts/generate_voice_clips.py --dry-run
    uv run scripts/generate_voice_clips.py --only narration
    uv run scripts/generate_voice_clips.py --only showcase
"""

import asyncio
import base64
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx
import tyro
from dotenv import load_dotenv

INWORLD_API = "https://api.inworld.ai/tts/v1/voice"

# (voice_id, text, language, speaking_rate)
# speaking_rate: 0.5–1.5, default 1.0

# --- Narrator lines (placed over capture scenes) ---
NARRATION: list[tuple[str, str, str, float]] = [
    ("Craig", "Articles, papers, books — just paste the link.", "en", 1.0),
    ("Deborah", "Listen to anything, in any voice you want!", "en", 1.0),
    ("Hana", "Make it yours.", "en", 1.0),
    ("Blake", "Try it now, on yapit.md!", "en", 1.0),
]

# --- Multilingual showcase (the voice cycling scene) ---
# Relay story told across languages — a morning vignette.
SHOWCASE: list[tuple[str, str, str, float]] = [
    ("Diego", "En más de quince idiomas.", "es", 1.5),  # "In more than fifteen languages."
    ("Asuka", "ある朝、彼女は窓を開けた。", "ja", 1.5),  # "One morning, she opened the window."
    ("Alain", "Ça sentait le café et la pluie.", "fr", 1.5),  # "It smelled of coffee and rain."
    ("Svetlana", "Она надела наушники.", "ru", 1.5),  # "She put on the headphones."
    ("Johanna", "Sie drückte auf Play.", "de", 1.5),  # "She pressed play."
    ("Gianni", "Una voce cominciò a leggere.", "it", 1.5),  # "A voice began to read."
    ("Xiaoyin", "一页，又一页。", "zh", 1.5),  # "One page, then another."
    ("Minji", "어느새 한 시간이 지났다.", "ko", 1.5),  # "Before she knew it, an hour had passed."
    ("Heitor", "E ela sorriu.", "pt", 1.5),  # "And she smiled."
]


@dataclass
class Args:
    model: str = "inworld-tts-1.5-max"
    """InWorld model ID. 'max' for quality, 'mini' for speed."""

    out_dir: str = "video/public/clips"
    """Base output directory."""

    dry_run: bool = False
    """Print config and exit without calling the API."""

    only: str = ""
    """Generate only 'narration' or 'showcase'. Empty = both."""

    sample_rate: int = 48000
    """Audio sample rate in Hz."""


async def get_duration(path: Path) -> float:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        str(path),
        stdout=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return float(json.loads(stdout)["format"]["duration"])


async def generate_clip(
    client: httpx.AsyncClient,
    api_key: str,
    voice_id: str,
    text: str,
    model_id: str,
    sample_rate: int,
    speaking_rate: float = 1.0,
) -> bytes:
    audio_config: dict = {"audioEncoding": "MP3", "sampleRateHertz": sample_rate}
    if speaking_rate != 1.0:
        audio_config["speakingRate"] = speaking_rate
    resp = await client.post(
        INWORLD_API,
        json={
            "text": text,
            "voiceId": voice_id,
            "modelId": model_id,
            "audioConfig": audio_config,
        },
        headers={"Authorization": f"Basic {api_key}"},
    )
    resp.raise_for_status()
    return base64.b64decode(resp.json()["audioContent"])


async def generate_set(
    name: str,
    lines: list[tuple[str, str, str, float]],
    out_dir: Path,
    client: httpx.AsyncClient,
    api_key: str,
    model: str,
    sample_rate: int,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []

    print(f"\n{'=' * 40}")
    print(f"  {name} ({len(lines)} clips)")
    print(f"{'=' * 40}")

    for i, (voice_id, text, lang, rate) in enumerate(lines):
        rate_tag = f" @{rate}x" if rate != 1.0 else ""
        print(f"  [{i + 1}/{len(lines)}] {voice_id} [{lang}]{rate_tag}: {text!r}")
        audio = await generate_clip(client, api_key, voice_id, text, model, sample_rate, rate)

        filename = f"{i:02d}-{voice_id.lower()}.mp3"
        path = out_dir / filename
        path.write_bytes(audio)

        duration = await get_duration(path)
        print(f"    → {path.name} ({duration:.2f}s)")

        manifest.append(
            {
                "index": i,
                "voice_id": voice_id,
                "text": text,
                "language": lang,
                "file": filename,
                "duration_s": duration,
                "speaking_rate": rate,
            }
        )

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    total = sum(v["duration_s"] for v in manifest)
    print(f"  Total: {total:.1f}s → {manifest_path}")


async def main_async(args: Args) -> None:
    load_dotenv(Path(__file__).parent.parent / ".env")
    api_key = os.getenv("INWORLD_API_KEY")
    if not api_key:
        print("ERROR: INWORLD_API_KEY not in .env")
        sys.exit(1)

    sets: list[tuple[str, list[tuple[str, str, str, float]], Path]] = []
    base = Path(args.out_dir)

    if args.only != "showcase":
        sets.append(("Narration", NARRATION, base / "narration"))
    if args.only != "narration":
        sets.append(("Showcase", SHOWCASE, base / "showcase"))

    if args.dry_run:
        for name, lines, out in sets:
            print(f"\n{name} → {out}/")
            for voice_id, text, lang, rate in lines:
                rate_tag = f" @{rate}x" if rate != 1.0 else ""
                print(f"  {voice_id:12s} [{lang}]{rate_tag}  {text!r}")
        return

    async with httpx.AsyncClient(timeout=30.0) as client:
        for name, lines, out in sets:
            await generate_set(name, lines, out, client, api_key, args.model, args.sample_rate)

    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main_async(tyro.cli(Args, default=Args(), description=__doc__)))

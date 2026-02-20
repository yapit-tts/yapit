# /// script
# requires-python = ">=3.12"
# dependencies = ["playwright==1.57.0", "tyro"]
# ///
"""Capture the real Yapit app as video clips + audio for the Remotion trailer.

Captures the full user journey in one recording, marking timestamps for key
moments so Remotion can trim into separate scenes:
  - home page visible
  - input submitted (URL or text pasted)
  - document loaded
  - play clicked
  - playback started

Auto-converts intercepted OGG audio to MP3 for Remotion compatibility.

Usage:
    uv run scripts/capture_trailer.py
    uv run scripts/capture_trailer.py --light-mode --duration 15
    uv run scripts/capture_trailer.py --url "https://arxiv.org/pdf/1706.03762"
    uv run scripts/capture_trailer.py --headed  # debug in visible browser
"""

import asyncio
import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

import tyro
from playwright.async_api import Response, async_playwright

DEMO_TEXT = """\
The transformer architecture has fundamentally changed how we process sequential \
data. Unlike recurrent neural networks that process tokens one at a time, \
transformers use self-attention to relate all positions in a sequence simultaneously.

At its core, the attention mechanism computes a weighted sum of values, where the \
weights are determined by the compatibility between queries and keys. This simple \
operation, scaled across multiple heads, enables the model to capture diverse \
linguistic patterns.

The impact has been staggering. From GPT to BERT to modern multimodal systems, \
nearly every breakthrough in AI over the past seven years traces back to the same \
elegant idea: attention is all you need.\
"""


@dataclass
class Args:
    base_url: str = "http://localhost:5173"
    """App base URL."""

    out_dir: str = "video/public/clips"
    """Output directory for captured clips."""

    duration: float = 12.0
    """Seconds of playback to record after clicking play."""

    width: int = 1920
    height: int = 1080

    url: str = ""
    """Paste a URL instead of text. If empty, uses --text."""

    text: str = DEMO_TEXT
    """Text content to create as a document (ignored if --url is set)."""

    headed: bool = False
    """Run in headed mode for debugging."""

    light_mode: bool = False
    """Capture in light mode (default is system/dark)."""

    settle_time: float = 1.0
    """Seconds to let the page settle before clicking play."""

    theme_cycle: bool = False
    """After playback starts, cycle through dark themes (charcoal → dusk → lavender).
    Output goes to darkmode.webm instead of playback.webm."""

    theme_hold: float = 1.5
    """Seconds to hold each theme during cycling."""

    auth: str = "video/.auth-state.json"
    """Playwright storage state file (cookies + localStorage).
    If missing, opens interactive browser for login first."""


@dataclass
class Markers:
    """Timestamps (seconds from recording start) for key moments."""

    recording_start: float = 0.0
    home_visible: float = 0.0
    input_submitted: float = 0.0
    document_loaded: float = 0.0
    play_clicked: float = 0.0
    playback_started: float = 0.0
    theme_cycle_start: float = 0.0


async def convert_ogg_to_mp3(ogg_path: Path) -> Path:
    """Convert OGG Opus to MP3 using ffmpeg."""
    mp3_path = ogg_path.with_suffix(".mp3")
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-i",
        str(ogg_path),
        "-codec:a",
        "libmp3lame",
        "-q:a",
        "2",
        str(mp3_path),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    if proc.returncode != 0:
        print(f"  WARNING: ffmpeg conversion failed for {ogg_path}")
        return ogg_path
    return mp3_path


async def get_audio_duration(path: Path) -> float:
    """Get audio duration in seconds via ffprobe."""
    try:
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
        info = json.loads(stdout)
        return float(info["format"]["duration"])
    except Exception:
        return 0.0


async def capture(args: Args) -> Path:
    """Record the full user journey. Returns path to the WebM clip."""
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    raw_dir = out / "_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    audio_dir = out / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    audio_files: list[dict] = []
    audio_counter = 0
    markers = Markers()

    async def on_response(response: Response) -> None:
        nonlocal audio_counter
        if "/v1/audio/" not in response.url:
            return
        if response.status != 200:
            return
        try:
            body = await response.body()
            variant_hash = response.url.split("/v1/audio/")[-1].split("?")[0]
            idx = audio_counter
            audio_counter += 1
            ogg_path = audio_dir / f"block-{idx:03d}.ogg"
            ogg_path.write_bytes(body)
            audio_files.append(
                {
                    "idx": idx,
                    "hash": variant_hash,
                    "ogg_path": str(ogg_path),
                    "size": len(body),
                }
            )
            print(f"  Captured audio block {idx} ({len(body)} bytes)")
        except Exception as e:
            print(f"  Failed to capture audio: {e}")

    t0 = 0.0  # reset when recording starts

    def mark(name: str) -> None:
        nonlocal t0
        elapsed = time.monotonic() - t0
        setattr(markers, name, round(elapsed, 2))
        print(f"  [{elapsed:.1f}s] {name}")

    auth_path = Path(args.auth)

    async with async_playwright() as p:
        # If no auth state exists, open interactive browser for login
        if not auth_path.exists():
            print(f"No auth state at {auth_path}. Opening browser — log in, then close it.")
            login_browser = await p.chromium.launch(headless=False)
            login_ctx = await login_browser.new_context()
            login_page = await login_ctx.new_page()
            await login_page.goto(args.base_url)
            # Wait for the browser to be closed manually
            try:
                await login_page.wait_for_event("close", timeout=300_000)
            except Exception:
                pass
            await login_ctx.storage_state(path=str(auth_path))
            await login_browser.close()
            print(f"Auth state saved to {auth_path}")

        browser = await p.chromium.launch(headless=not args.headed)
        context = await browser.new_context(
            viewport={"width": args.width, "height": args.height},
            record_video_dir=str(raw_dir),
            record_video_size={"width": args.width, "height": args.height},
            color_scheme="light" if args.light_mode else "dark",
            storage_state=str(auth_path),
        )

        # Start with sidebar closed + dismiss WebGPU banner
        await context.add_cookies(
            [
                {
                    "name": "sidebar_state",
                    "value": "false",
                    "url": args.base_url,
                }
            ]
        )
        await context.add_init_script("""
            window.addEventListener('DOMContentLoaded', () => {
                localStorage.setItem('yapit_webgpu_warning_dismissed', 'true');
                localStorage.setItem('yapit_voice_selection', JSON.stringify({
                    model: 'inworld-1.5', voiceSlug: 'Ashley'
                }));
            });
        """)

        page = await context.new_page()
        page.on("response", on_response)

        markers.recording_start = 0.0
        t0 = time.monotonic()

        # Navigate to home page
        print(f"Navigating to {args.base_url}")
        await page.goto(args.base_url, wait_until="networkidle")
        mark("home_visible")

        # Dismiss any banners
        try:
            close_btns = page.locator("svg.lucide-x").locator("..")
            await close_btns.first.click(timeout=2000)
        except Exception:
            pass

        # Input: URL or text
        textarea = page.get_by_placeholder("Paste a URL, drop a file, or type text...")
        await textarea.click()
        content = args.url if args.url else args.text
        await textarea.fill(content)
        await page.wait_for_timeout(500)

        if not args.url:
            # Text mode: click "Start Listening"
            start_btn = page.get_by_role("button", name="Start Listening")
            await start_btn.click()
        # URL mode: auto-navigates after extraction
        mark("input_submitted")

        # Wait for document to load
        print("Waiting for document to load...")
        await page.wait_for_url("**/listen/**", timeout=60_000)
        await page.wait_for_selector("[data-audio-block-idx]", timeout=30_000)

        # Let the page settle
        await page.wait_for_timeout(int(args.settle_time * 1000))
        mark("document_loaded")

        # Click play
        print("Starting playback...")
        play_btn = page.locator("button:has(svg.lucide-play)")
        await play_btn.click(timeout=5000)
        mark("play_clicked")

        if args.theme_cycle:
            # Brief wait for synthesis to start and highlighting to appear
            await page.wait_for_timeout(2000)
            mark("playback_started")
        else:
            # Wait for synthesis to start (spinner appears, then pause icon)
            try:
                await page.wait_for_selector("svg.lucide-loader-2, svg.lucide-pause", timeout=10_000)
                mark("playback_started")
            except Exception:
                print("WARNING: Could not detect playback start, continuing")
                markers.playback_started = markers.play_clicked + 1.0

        if args.theme_cycle:
            hold_ms = int(args.theme_hold * 1000)
            # Start in light mode (already there), cycle through dark themes
            themes = [
                ("charcoal", "el.classList.add('dark'); el.className = el.className.replace(/theme-\\S+/g, '');"),
                ("dusk", "el.className = el.className.replace(/theme-\\S+/g, ''); el.classList.add('theme-dusk');"),
                (
                    "lavender",
                    "el.className = el.className.replace(/theme-\\S+/g, ''); el.classList.add('theme-lavender');",
                ),
            ]

            # Hold light mode briefly before first transition
            mark("theme_cycle_start")
            await page.wait_for_timeout(hold_ms)

            print("Theme cycling:")
            for name, js_code in themes:
                js = f"() => {{ const el = document.documentElement; {js_code} }}"
                await page.evaluate(js)
                elapsed = time.monotonic() - t0
                print(f"  [{elapsed:.1f}s] → {name}")
                await page.wait_for_timeout(hold_ms)

            # Hold last theme
            await page.wait_for_timeout(hold_ms)
        else:
            # Record playback, pressing "j" to advance blocks so highlighting moves
            print(f"Recording {args.duration}s of playback (pressing j to advance)...")
            elapsed = 0.0
            step = 1.5  # seconds between j presses
            while elapsed < args.duration:
                wait = min(step, args.duration - elapsed)
                await page.wait_for_timeout(int(wait * 1000))
                elapsed += wait
                if elapsed < args.duration:
                    await page.keyboard.press("j")
                    print(f"  [{time.monotonic() - t0:.1f}s] pressed j")

        # Finalize
        video_path_str = await page.video.path()
        await context.close()
        await browser.close()

    # Move video to final location
    video_filename = "darkmode.webm" if args.theme_cycle else "playback.webm"
    final_path = out / video_filename
    shutil.move(str(video_path_str), str(final_path))
    if raw_dir.exists():
        shutil.rmtree(raw_dir, ignore_errors=True)

    # Convert OGG→MP3 and get durations
    print("\nConverting audio to MP3...")
    for af in audio_files:
        ogg_path = Path(af["ogg_path"])
        mp3_path = await convert_ogg_to_mp3(ogg_path)
        af["mp3_path"] = str(mp3_path)
        af["duration_s"] = await get_audio_duration(mp3_path)
        print(f"  block-{af['idx']:03d}: {af['duration_s']:.2f}s")

    # Write metadata
    meta = {
        "video": str(final_path),
        "light_mode": args.light_mode,
        "markers": {
            "home_visible": markers.home_visible,
            "input_submitted": markers.input_submitted,
            "document_loaded": markers.document_loaded,
            "play_clicked": markers.play_clicked,
            "playback_started": markers.playback_started,
            "theme_cycle_start": markers.theme_cycle_start,
        },
        "audio": [
            {
                "idx": af["idx"],
                "hash": af["hash"],
                "path": af["ogg_path"],
                "size": af["size"],
                "duration_s": af["duration_s"],
            }
            for af in audio_files
        ],
        "total_audio_duration_s": sum(af["duration_s"] for af in audio_files),
    }
    meta_filename = "meta-darkmode.json" if args.theme_cycle else "meta.json"
    meta_path = out / meta_filename
    meta_path.write_text(json.dumps(meta, indent=2))

    print("\nCapture complete:")
    print(f"  Video: {final_path}")
    print(f"  Audio blocks: {len(audio_files)}")
    print(f"  Total audio: {meta['total_audio_duration_s']:.2f}s")
    print(f"  Markers: {json.dumps(meta['markers'], indent=4)}")
    print(f"  Metadata: {meta_path}")

    return final_path


async def main_async(args: Args) -> None:
    clip = await capture(args)
    print(f"\nDone! Clip at: {clip}")
    print("Next: cd video && npx remotion studio")


def main() -> None:
    args = tyro.cli(Args)
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()

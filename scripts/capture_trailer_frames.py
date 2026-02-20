# /// script
# requires-python = ">=3.12"
# dependencies = ["playwright", "tyro"]
# ///
"""Capture the real Yapit app frame-by-frame for the Remotion trailer.

Puppeteer-style capture: opens the real app in a browser, manipulates DOM state
per frame (active block highlight, scroll position), and screenshots each frame.

The playbar is hidden during capture — Remotion renders it as an overlay for
full control over progress animation.

Usage:
    uv run scripts/capture_trailer_frames.py --url "http://localhost:5173/documents/{id}"
    uv run scripts/capture_trailer_frames.py --url "http://localhost:5173/documents/{id}" --fps 30 --out video/public/captures/doc
"""

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

import tyro
from playwright.async_api import async_playwright


@dataclass
class Args:
    url: str
    """Document page URL (e.g. http://localhost:5173/documents/{uuid})"""

    out: str = "video/public/captures/doc"
    """Output directory for frame PNGs"""

    fps: int = 30
    """Frames per second"""

    duration: float | None = None
    """Total capture duration in seconds. If None, computed from block durations."""

    width: int = 1920
    height: int = 1080

    wait_for_content: float = 5.0
    """Seconds to wait for .structured-content to appear"""

    hide_playbar: bool = True
    """Hide the playbar during capture (render it in Remotion instead)"""


async def capture(args: Args) -> None:
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": args.width, "height": args.height})

        print(f"Navigating to {args.url}")
        await page.goto(args.url, wait_until="networkidle")

        # Wait for document content to render
        print("Waiting for .structured-content...")
        await page.wait_for_selector(".structured-content", timeout=args.wait_for_content * 1000)
        # Extra settle time for fonts/images
        await page.wait_for_timeout(1000)

        if args.hide_playbar:
            # Hide the fixed playbar so Remotion can render its own
            await page.evaluate("""() => {
                const playbar = document.querySelector('[class*="fixed"][class*="bottom-0"]');
                if (playbar) playbar.style.display = 'none';
                // Also remove the bottom padding that accounts for playbar
                const content = document.querySelector('.structured-content');
                if (content) content.style.paddingBottom = '100px';
            }""")

        # Extract block info: indices, positions, estimated durations
        block_data = await page.evaluate("""() => {
            const blockEls = document.querySelectorAll('[data-audio-block-idx]');
            const innerEls = document.querySelectorAll('[data-audio-idx]');

            // Prefer inner spans if they exist, otherwise block-level
            const elements = innerEls.length > 0 ? innerEls : blockEls;
            const attrName = innerEls.length > 0 ? 'audioIdx' : 'audioBlockIdx';

            return Array.from(elements).map(el => ({
                idx: parseInt(el.dataset[attrName]),
                top: el.getBoundingClientRect().top + window.scrollY,
                height: el.getBoundingClientRect().height,
            }));
        }""")

        if not block_data:
            print("ERROR: No audio blocks found on page. Is a document loaded?")
            await browser.close()
            return

        n_blocks = len(block_data)
        print(f"Found {n_blocks} audio blocks")

        # Try to get real durations from the playback engine if available
        durations_ms = await page.evaluate("""() => {
            // The playback engine stores block data — try to access it
            // This is fragile and depends on the app's internal state
            try {
                // Look for block data in any accessible global or DOM data
                const blocks = window.__YAPIT_BLOCKS__;
                if (blocks) return blocks.map(b => b.est_duration_ms);
            } catch {}
            return null;
        }""")

        if not durations_ms:
            # Estimate: ~14 chars/second for TTS
            print("Using estimated durations (no real duration data available)")
            durations_ms = []
            for bd in block_data:
                # Rough estimate based on vertical size as proxy for text length
                est_chars = max(bd["height"] * 3, 50)  # ~3 chars per pixel height
                durations_ms.append(max(500, int(est_chars / 14 * 1000)))

        total_ms = sum(durations_ms)
        total_duration = args.duration or (total_ms / 1000)
        total_frames = int(total_duration * args.fps)

        print(f"Capturing {total_frames} frames ({total_duration:.1f}s at {args.fps}fps)")
        print(f"Total estimated audio: {total_ms / 1000:.1f}s")

        # Precompute cumulative durations for frame-to-block mapping
        cumulative_ms = []
        acc = 0
        for d in durations_ms:
            acc += d
            cumulative_ms.append(acc)

        # Get viewport height for scroll calculation
        viewport_h = args.height

        # Capture each frame
        for frame in range(total_frames):
            elapsed_ms = (frame / args.fps) * 1000

            # Determine active block
            active_idx = 0
            for i, cum in enumerate(cumulative_ms):
                if cum > elapsed_ms:
                    active_idx = i
                    break
            else:
                active_idx = n_blocks - 1

            active_block = block_data[min(active_idx, n_blocks - 1)]

            # Inject: set active block highlight + scroll position
            await page.evaluate(
                """({activeIdx, scrollTarget, attrName}) => {
                // Remove all existing highlights
                document.querySelectorAll('.audio-block-active').forEach(el =>
                    el.classList.remove('audio-block-active'));

                // Add highlight to active block
                const selector = attrName === 'audioIdx'
                    ? `[data-audio-idx="${activeIdx}"]`
                    : `[data-audio-block-idx="${activeIdx}"]`;
                const el = document.querySelector(selector);
                if (el) el.classList.add('audio-block-active');

                // Smooth scroll to keep active block in upper third
                window.scrollTo({ top: scrollTarget, behavior: 'instant' });
            }""",
                {
                    "activeIdx": block_data[min(active_idx, n_blocks - 1)]["idx"],
                    "scrollTarget": max(0, active_block["top"] - viewport_h * 0.3),
                    "attrName": "audioIdx"
                    if len(block_data) > 0 and "audioIdx" in str(block_data[0])
                    else "audioBlockIdx",
                },
            )

            # Small settle time for any CSS to apply
            if frame % 30 == 0:
                await page.wait_for_timeout(50)

            # Screenshot
            frame_path = out_dir / f"frame-{frame:05d}.png"
            await page.screenshot(path=str(frame_path))

            if frame % args.fps == 0:
                print(f"  Frame {frame}/{total_frames} ({frame / args.fps:.0f}s)")

        print(f"Done! {total_frames} frames saved to {out_dir}")

        # Save metadata for Remotion
        meta = {
            "fps": args.fps,
            "totalFrames": total_frames,
            "totalDurationMs": total_ms,
            "blocks": [{"idx": bd["idx"], "durationMs": d} for bd, d in zip(block_data, durations_ms)],
            "width": args.width,
            "height": args.height,
        }
        meta_path = out_dir / "meta.json"
        meta_path.write_text(json.dumps(meta, indent=2))
        print(f"Metadata saved to {meta_path}")

        await browser.close()


async def capture_feature_screenshots(page, out_dir: Path) -> None:
    """Capture static screenshots of feature states (voice picker, dark mode, etc.)

    TODO: implement when we have specific feature URLs/states to capture.
    """
    pass


def main() -> None:
    args = tyro.cli(Args)
    asyncio.run(capture(args))


if __name__ == "__main__":
    main()

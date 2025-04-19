import argparse
import asyncio
import pathlib
import wave

import httpx
import websockets

GATEWAY = "http://localhost:8000"


async def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke test for TTS pipeline")
    parser.add_argument(
        "--model",
        choices=["kokoro-gpu", "kokoro-cpu"],
        default="kokoro-gpu",
        help="Model to test (default: kokoro-gpu)",
    )
    args = parser.parse_args()

    # 1. enqueue a job
    async with httpx.AsyncClient() as client:
        model_key = "kokoro" if args.model == "kokoro-gpu" else "kokoro-cpu"
        resp = await client.post(
            f"{GATEWAY}/v1/tts",
            json={
                "model": "kokoro-cpu",
                "text": f"Hello world, this is {model_key} speaking..",
            },
        )

    resp.raise_for_status()
    ws_url = f"{GATEWAY.replace('http', 'ws')}{resp.json()['ws_url']}"

    # 2. open WebSocket and collect ~2 s of audio
    pcm_frames: bytearray = bytearray()
    async with websockets.connect(ws_url, max_size=2**24) as ws:
        async for msg in ws:
            if isinstance(msg, bytes):
                pcm_frames.extend(msg)
            if len(pcm_frames) > 2 * 24000 * 2:  # 2 s * 24 kHz * int16
                break
    print("pcm_frames: ", pcm_frames)

    # 3. dump to WAV for a quick ears-on test
    out = pathlib.Path("sample.wav").open("wb")
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)  # int16
        wav.setframerate(24_000)
        wav.writeframes(pcm_frames)
    print("wrote sample.wav  ✓")


if __name__ == "__main__":
    asyncio.run(main())

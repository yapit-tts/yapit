import asyncio
import httpx
import pathlib
import wave
import websockets

GATEWAY = "http://localhost:8000"


async def main() -> None:
    # 1. enqueue a job
    print("before enqueue")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GATEWAY}/v1/tts",
            json={"text": "Hello world, this is Yapit speaking."},
        )
    print("after enqueue")
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

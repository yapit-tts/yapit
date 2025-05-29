import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
import redis as _redis
import requests
import websocket


def test_synthesize_route_only(app: FastAPI):
    client = TestClient(app=app)

    # 1. create doc
    doc = client.post(
        f"/v1/documents",
        json={"source_type": "paste", "text_content": "Hello Yapit"},
        timeout=5,
    ).json()
    # extract document and block IDs
    document_id = doc["document_id"]
    block_id = doc["blocks"][0]["id"]

    # 2. enqueue synthesis
    synth = client.post(
        f"/v1/documents/{document_id}/blocks/{block_id}/synthesize",
        json={"model_slug": "kokoro", "voice_slug": "af_heart", "speed": 1.0},
        timeout=5,
    )
    # API contract only: 201, JSON keys present
    assert synth.status_code == 201
    j = synth.json()
    assert {"variant_hash", "ws_url", "est_duration_ms"} <= j.keys()

    # 3. ensure WS endpoint accepts the handshake (no audio expected)
    ws = client.websocket_connect(j["ws_url"], timeout=5)
    ws.close()


def test_streaming_audio(wait_until_gateway, gateway_url: str, ws_url: str):
    # 1. create doc & enqueue synthesis
    doc = requests.post(
        f"{gateway_url}/v1/documents",
        json={"source_type": "paste", "text_content": "Ping Pong"},
        timeout=5,
    ).json()
    document_id = doc["document_id"]
    block_id = doc["blocks"][0]["id"]
    synth = requests.post(
        f"{gateway_url}/v1/documents/{document_id}/blocks/{block_id}/synthesize",
        json={"model_slug": "kokoro", "voice_slug": "af_heart", "speed": 1.0},
        timeout=5,
    ).json()

    variant = synth["variant_hash"]
    path = synth["ws_url"]

    # 2. open WebSocket
    ws = websocket.create_connection(f"{ws_url}{path}", timeout=5)

    # 3. publish two chunks into Redis (stream channel)
    r = _redis.Redis(host="localhost", port=6379)
    chunks = [b"chunk1", b"chunk2"]
    # small pause to ensure server subscription is set up
    time.sleep(0.1)
    for c in chunks:
        r.publish(f"tts:{variant}:stream", c)

    # 4. receive and verify
    received = [ws.recv() for _ in chunks]
    ws.close()
    assert received == chunks

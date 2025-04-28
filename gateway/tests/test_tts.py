import requests
import websocket

from .conftest import GATEWAY, WS


def test_synthesize_route_only():
    # 1. create doc
    doc = requests.post(
        f"{GATEWAY}/v1/documents",
        json={"source_type": "paste", "text_content": "Hello Yapit"},
        timeout=5,
    ).json()
    block_id = doc["blocks"][0]["id"]

    # 2. enqueue synthesis (we don't care if a worker is attached)
    synth = requests.post(
        f"{GATEWAY}/v1/blocks/{block_id}/synthesize",
        json={"model_slug": "kokoro", "voice_slug": "af_heart", "speed": 1.0, "codec": "pcm"},
        timeout=5,
    )
    # API contract only: 201, JSON keys present
    assert synth.status_code == 201
    j = synth.json()
    assert {"variant_id", "ws_url", "est_ms"} <= j.keys()

    # 3. ensure WS endpoint accepts the handshake (no audio expected)
    ws = websocket.create_connection(f"{WS}{j['ws_url']}", timeout=5)
    ws.close()

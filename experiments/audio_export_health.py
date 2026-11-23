"""Time saving the benchmark's ten-hour selection through the gateway, and health requests while it is built.

Runs the gateway as the API tests do, in this process, with the blocks in Redis, and drives it
through the HTTP API: the export request, health requests one after another until the build has
ended, then the request for the file. Prints the time from the export request to the file's last
byte and each phase's health latencies, and appends them to the file OUT names, if set. SPEECH and
SCRATCH are the benchmark's --speech and --scratch. SECTIONS saves only the first so many of the
selection's 30 sections, and BUSY runs that many busy loops at normal priority on the same cores
throughout, as synthesis loads production's.

    uv run pytest experiments/audio_export_health.py -p tests.yapit.gateway.api.conftest -s
"""

import asyncio
import importlib.util
import json
import os
import statistics
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from tests.yapit.gateway.api.conftest import DEFAULT_TEST_USER
from yapit.contracts import TTS_AUDIO_CACHE, get_pubsub_channel
from yapit.gateway.domain_models import BlockVariant, Document, TTSModel, Voice


def _benchmark():
    spec = importlib.util.spec_from_file_location(
        "audio_export_benchmark", Path(__file__).with_name("audio_export_benchmark.py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _health_latencies(client, until: asyncio.Future | None = None, count: int = 200) -> list[float]:
    latencies = []
    while (until is None and len(latencies) < count) or (until is not None and not until.done()):
        started = time.perf_counter()
        response = await client.get("/health")
        latencies.append(time.perf_counter() - started)
        assert response.status_code == 200
        await asyncio.sleep(0.02)
    return latencies


def _summary(latencies: list[float]) -> dict:
    ms = sorted(x * 1000 for x in latencies)
    return {
        "requests": len(ms),
        "p50_ms": round(statistics.median(ms), 2),
        "p99_ms": round(ms[int(len(ms) * 0.99) - 1], 2),
        "max_ms": round(ms[-1], 2),
    }


@pytest.fixture
def busy_loops():
    command = [sys.executable, "-c", "while True: pass"]
    loops = [subprocess.Popen(command) for _ in range(int(os.environ.get("BUSY", "0")))]
    yield len(loops)
    for loop in loops:
        loop.kill()


@pytest.mark.parametrize("fmt", ["m4b", "mp3"])
async def test_health_while_a_ten_hour_selection_is_built(client, app, session, fmt, busy_loops):
    bench = _benchmark()
    blocks, sections = bench.corpus(Path(os.environ["SPEECH"]), "ten-hours", Path(os.environ["SCRATCH"]))
    sections = sections[: int(os.environ.get("SECTIONS", len(sections)))]
    model = TTSModel(slug="kokoro", name="Kokoro")
    voice = Voice(slug="af_heart", name="Heart", lang="en-us", model=model)
    session.add_all([model, voice])
    await session.commit()

    hashes = [h for _, section in sections for h in section]
    content = "\n\n".join(f"Paragraph {i} of the book is read aloud." for i in range(len(hashes)))
    response = await client.post("/v1/documents/text", json={"content": content, "title": "A Long Book"})
    document_id = uuid.UUID(response.json()["id"])
    texts = (await session.get(Document, document_id)).audio_texts
    assert len(texts) == len(hashes)
    redis = app.state.redis_client
    for text, h in zip(texts, hashes):
        variant = BlockVariant.get_hash(
            text=text, model_slug="kokoro", voice_slug="af_heart", parameters=voice.parameters
        )
        await redis.set(TTS_AUDIO_CACHE.format(hash=variant), blocks[h])

    idle = await _health_latencies(client)

    pubsub = redis.pubsub()
    await pubsub.subscribe(get_pubsub_channel(DEFAULT_TEST_USER.id, document_id))
    await pubsub.get_message(timeout=1)
    ranges, first = [], 0
    for title, section in sections:
        ranges.append({"first_block": first, "last_block": first + len(section) - 1, "title": title})
        first += len(section)
    started = time.perf_counter()
    state = (
        await client.post(
            f"/v1/documents/{document_id}/audio-export",
            json={"model": "kokoro", "voice": "af_heart", "format": fmt, "ranges": ranges},
        )
    ).json()
    assert state["status"] == "building", state

    async def built() -> dict:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=3600)
            heard = json.loads(message["data"]) if message else {}
            if heard.get("key") == state["key"] and heard["status"] != "building":
                return heard

    done = asyncio.ensure_future(built())
    building = await _health_latencies(client, until=done)
    ended = done.result()
    build_s = time.perf_counter() - started
    await pubsub.aclose()
    assert ended["status"] == "ready", ended
    file = await client.get(f"/v1/documents/{document_id}/audio-export/{state['key']}.{fmt}")
    save_s = time.perf_counter() - started
    assert file.status_code == 200

    result = {
        "format": fmt,
        "audio_s": round(sum(bench._samples(blocks[h]) for h in hashes) / bench.RATE),
        "cores": len(os.sched_getaffinity(0)),
        "busy_loops": busy_loops,
        "build_s": round(build_s, 1),
        "save_to_file_s": round(save_s, 1),
        "file_mb": round(len(file.content) / 1e6, 1),
        "idle": _summary(idle),
        "building": _summary(building),
    }
    print(json.dumps(result))
    if out := os.environ.get("OUT"):
        with open(out, "a") as f:
            f.write(json.dumps({"measurement": "saving a selection, and health meanwhile", **result}) + "\n")

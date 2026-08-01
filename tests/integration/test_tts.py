import time

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model_slug,voice_slug",
    [
        ("kokoro", "af_heart"),
    ],
)
async def test_tts_integration(model_slug, voice_slug, subscribed_ws_client, subscribed_client, test_document):
    """Test complete TTS flow via WebSocket from document creation to audio retrieval."""
    document_id = test_document["id"]
    block_idx = test_document["blocks"][0]["idx"]

    start_time = time.time()
    audio_url = await synthesize_block_to_audio_url(
        subscribed_ws_client, document_id, block_idx, model_slug, voice_slug
    )
    elapsed = time.time() - start_time
    print(f"Synthesis took {elapsed:.2f} seconds")

    # Fetch audio via HTTP GET
    audio_response = await subscribed_client.get(audio_url)
    assert audio_response.status_code == 200
    assert "audio/" in audio_response.headers["content-type"]
    assert len(audio_response.content) > 0
    assert any(b != 0 for b in audio_response.content)

    # Request same block again - should return cached immediately
    subscribed_ws_client.messages.clear()
    start_time = time.time()

    await subscribed_ws_client.synthesize(
        document_id=document_id,
        block_indices=[block_idx],
        model=model_slug,
        voice=voice_slug,
    )

    cached_status = await subscribed_ws_client.wait_for_status(block_idx, "cached", timeout=5.0)
    elapsed = time.time() - start_time
    print(f"Cached synthesis took {elapsed:.2f} seconds")

    assert cached_status is not None
    assert cached_status["audio_url"] == audio_url


@pytest.mark.asyncio
async def test_tts_non_english_voices(subscribed_ws_client, subscribed_client):
    """Regression for #87: non-English voices must use their language's G2P pipeline.

    Before the fix all voices ran through the American English pipeline: everything was
    phonemized as English (Latin text got English pronunciation regardless of voice),
    pure-CJK blocks ended as "skipped" with no audio, and in mixed text each CJK glyph
    was spoken as "japanese letter"/"chinese letter" via the espeak fallback.

    One document with one paragraph (= block) per language.
    """
    cases = [
        ("ef_dora", "El veloz murciélago comía feliz cardillo y kiwi."),
        ("jf_alpha", "今日はいい天気ですね。散歩に行きましょう。"),
        ("zf_xiaobei", "今天天气很好，我们去散步吧。"),
    ]
    content = "\n\n".join(text for _, text in cases)
    response = await subscribed_client.post("/v1/documents/text", json={"content": content})
    assert response.status_code == 201
    doc = response.json()

    blocks_response = await subscribed_client.get(f"/v1/documents/{doc['id']}/blocks")
    assert blocks_response.status_code == 200
    blocks = blocks_response.json()
    assert len(blocks) == len(cases), f"Expected one block per paragraph, got {blocks}"

    for (voice_slug, _), block in zip(cases, blocks, strict=True):
        audio_url = await synthesize_block_to_audio_url(
            subscribed_ws_client, doc["id"], block["idx"], "kokoro", voice_slug
        )
        audio_response = await subscribed_client.get(audio_url)
        assert audio_response.status_code == 200
        assert len(audio_response.content) > 0, f"{voice_slug}: empty audio"


@pytest.mark.asyncio
async def test_degenerate_text_skipped_not_crashed(subscribed_ws_client, subscribed_client):
    """Regression: text that produces no audio must be skipped, not crash the worker.

    Before the Opus encoding change (1d69419), empty PCM from Kokoro flowed
    through as audio_base64="" and the result consumer marked it "skipped".
    After Opus, _pcm_to_ogg_opus crashed on the 0-sample frame with MemoryError,
    turning a skip into a synthesis error with retries.
    """
    text = "<"
    response = await subscribed_client.post("/v1/documents/text", json={"content": text})
    assert response.status_code == 201
    doc = response.json()

    blocks_response = await subscribed_client.get(f"/v1/documents/{doc['id']}/blocks")
    assert blocks_response.status_code == 200
    blocks = blocks_response.json()
    assert len(blocks) > 0

    block_idx = blocks[0]["idx"]
    await subscribed_ws_client.synthesize(
        document_id=doc["id"],
        block_indices=[block_idx],
        model="kokoro",
        voice="af_heart",
    )

    status_msg = await subscribed_ws_client.wait_for_any_status(block_idx, timeout=30.0)
    assert status_msg is not None, f"No status received for degenerate text {text!r}"

    # Must reach skipped (empty audio) — not error (crash)
    if status_msg["status"] == "queued":
        final = await subscribed_ws_client.wait_for_status(block_idx, "skipped", timeout=30.0)
        if final is None:
            # Check if it errored instead
            errors = [
                m
                for m in subscribed_ws_client.messages
                if m.get("block_idx") == block_idx and m.get("status") == "error"
            ]
            assert not errors, f"Degenerate text {text!r} caused error instead of skip: {errors}"
            pytest.fail(f"Degenerate text {text!r}: expected 'skipped', got neither skipped nor error")
    else:
        assert status_msg["status"] == "skipped", (
            f"Degenerate text {text!r}: expected 'skipped', got {status_msg['status']!r}"
        )


async def synthesize_block_to_audio_url(ws_client, document_id: str, block_idx: int, model: str, voice: str) -> str:
    """Synthesize one block via WebSocket and wait until its audio is cached."""
    await ws_client.synthesize(
        document_id=document_id,
        block_indices=[block_idx],
        model=model,
        voice=voice,
    )

    status_msg = await ws_client.wait_for_any_status(block_idx, timeout=10.0)
    assert status_msg is not None, f"{voice}: no status message received"
    assert status_msg["status"] in ("queued", "cached"), f"Unexpected status: {status_msg}"

    if status_msg["status"] == "cached":
        return status_msg["audio_url"]
    cached_msg = await ws_client.wait_for_status(block_idx, "cached", timeout=120.0)
    assert cached_msg is not None, f"{voice}: synthesis did not produce audio (skipped or timed out)"
    return cached_msg["audio_url"]

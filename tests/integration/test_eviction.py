"""Integration tests for TTS eviction (cursor_moved) behavior."""

import asyncio

import pytest


@pytest.fixture
async def multi_block_document(admin_client):
    """Create a document with multiple blocks for eviction testing."""
    # Each paragraph becomes a separate block
    paragraphs = [f"This is test paragraph number {i}. It has enough words to be a block." for i in range(30)]
    content = "\n\n".join(paragraphs)

    response = await admin_client.post(
        "/v1/documents/text",
        json={"content": content},
    )
    assert response.status_code == 201
    doc = response.json()

    blocks_response = await admin_client.get(f"/v1/documents/{doc['id']}/blocks")
    assert blocks_response.status_code == 200
    doc["blocks"] = blocks_response.json()

    assert len(doc["blocks"]) >= 28, f"Expected at least 28 blocks, got {len(doc['blocks'])}"
    return doc


@pytest.mark.asyncio
async def test_cursor_moved_sends_evicted_message(admin_ws_client, multi_block_document):
    """Test that cursor_moved evicts blocks outside the window and sends WSEvicted."""
    document_id = multi_block_document["id"]
    blocks = multi_block_document["blocks"]

    # Request blocks 0-7 with cursor at 0
    block_indices = [b["idx"] for b in blocks[:8]]
    await admin_ws_client.synthesize(
        document_id=document_id,
        block_indices=block_indices,
        cursor=0,
    )

    # Wait briefly for queued status
    await asyncio.sleep(0.5)

    # Move cursor far away (to block 25)
    # Window becomes [25-8, 25+16] = [17, 41]
    # Blocks 0-7 should be outside this window
    await admin_ws_client.cursor_moved(document_id, cursor=25)

    # Wait for evicted message
    evicted_msg = await admin_ws_client.wait_for_evicted(timeout=5.0)

    assert evicted_msg is not None, "Expected WSEvicted message"
    assert evicted_msg["document_id"] == document_id
    # At least some of blocks 0-7 should be evicted (those not yet processed)
    assert len(evicted_msg["block_indices"]) > 0, "Expected some blocks to be evicted"
    # All evicted blocks should be < 17 (outside window)
    for idx in evicted_msg["block_indices"]:
        assert idx < 17, f"Block {idx} should not be evicted (inside window)"


@pytest.mark.asyncio
async def test_evicted_blocks_not_synthesized(admin_ws_client, admin_client, multi_block_document):
    """Test that evicted blocks are skipped by the worker (don't become cached)."""
    document_id = multi_block_document["id"]
    blocks = multi_block_document["blocks"]

    # Request blocks 0-7 with cursor at 0
    block_indices = [b["idx"] for b in blocks[:8]]
    await admin_ws_client.synthesize(
        document_id=document_id,
        block_indices=block_indices,
        cursor=0,
    )

    # Immediately move cursor far away before worker can process
    await admin_ws_client.cursor_moved(document_id, cursor=25)

    # Wait for evicted message
    evicted_msg = await admin_ws_client.wait_for_evicted(timeout=5.0)
    evicted_indices = set(evicted_msg["block_indices"]) if evicted_msg else set()

    # Wait some time for any synthesis to complete
    await asyncio.sleep(3.0)

    # Check which blocks got cached status
    cached_indices = set()
    for msg in admin_ws_client.get_status_messages():
        if msg.get("status") == "cached":
            cached_indices.add(msg["block_idx"])

    # Evicted blocks should NOT be in cached set
    # (they were skipped by worker)
    wrongly_cached = evicted_indices & cached_indices
    assert len(wrongly_cached) == 0, f"Evicted blocks {wrongly_cached} were still synthesized"


@pytest.mark.asyncio
async def test_cursor_moved_no_eviction_within_window(admin_ws_client, multi_block_document):
    """Test that cursor_moved within window doesn't evict blocks."""
    document_id = multi_block_document["id"]
    blocks = multi_block_document["blocks"]

    # Request blocks 0-7 with cursor at 0
    block_indices = [b["idx"] for b in blocks[:8]]
    await admin_ws_client.synthesize(
        document_id=document_id,
        block_indices=block_indices,
        cursor=0,
    )

    # Move cursor to 5 (still within window)
    # Window becomes [5-8, 5+16] = [-3, 21]
    # Blocks 0-7 are still inside
    await admin_ws_client.cursor_moved(document_id, cursor=5)

    # Wait briefly
    await asyncio.sleep(0.5)

    # Should NOT receive evicted message
    evicted_msgs = admin_ws_client.get_evicted_messages()
    assert len(evicted_msgs) == 0, "Should not evict blocks within window"


@pytest.mark.asyncio
async def test_blocks_after_window_also_evicted(admin_ws_client, multi_block_document):
    """Test that blocks ahead of cursor+buffer_ahead are also evicted."""
    document_id = multi_block_document["id"]
    blocks = multi_block_document["blocks"]

    # Request blocks 20-27 with cursor at 20
    block_indices = [b["idx"] for b in blocks[20:28]]
    await admin_ws_client.synthesize(
        document_id=document_id,
        block_indices=block_indices,
        cursor=20,
    )

    await asyncio.sleep(0.5)

    # Move cursor back to 0
    # Window becomes [0-8, 0+16] = [-8, 16]
    # Blocks 20-27 should be outside (> 16)
    await admin_ws_client.cursor_moved(document_id, cursor=0)

    evicted_msg = await admin_ws_client.wait_for_evicted(timeout=5.0)

    assert evicted_msg is not None, "Expected WSEvicted message"
    # All evicted blocks should be > 16 (outside window)
    for idx in evicted_msg["block_indices"]:
        assert idx > 16, f"Block {idx} should not be evicted (inside window)"

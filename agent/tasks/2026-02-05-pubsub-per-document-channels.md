---
status: done
started: 2026-02-05
---

# Task: Per-document pubsub channels for TTS status notifications

## Intent

The TTS pubsub channel is currently per-user (`tts:done:{user_id}`). ALL WebSocket connections for a user receive ALL synthesis notifications regardless of which document they belong to. This causes cross-document contamination: if a user has two tabs open, Tab B can receive and act on Tab A's block completions.

The fix: publish to `tts:done:{user_id}:{document_id}` and subscribe per-document. Correct by construction — clients cannot receive cross-document messages.

## Assumptions

- The frontend WebSocket code does NOT need routing changes. The server handles per-document pubsub subscription transparently — when a `synthesize` message arrives with a `document_id`, the server subscribes the connection to that document's channel. The frontend has no awareness of Redis pubsub.
- The frontend DOES need a small semantic fix: `pendingKey` in `serverSynthesizer.ts` should include `documentId` because a pending synthesis identifies a block *in a document*. Currently `${blockIdx}:${model}:${voice}` — should be `${documentId}:${blockIdx}:${model}:${voice}`.
- Redis handles many subscriptions per client efficiently. Accumulating per-document subscriptions over a WebSocket session's lifetime is fine.

## Sources

**Knowledge files:**
- [[tts-flow]] — TTS pipeline architecture, pubsub notification flow

**Key code files:**
- MUST READ: `yapit/contracts.py:53-54` — `get_pubsub_channel()` definition (currently per-user)
- MUST READ: `yapit/gateway/result_consumer.py:157-193` — `_notify_subscribers()` publishes to channel. Already has `doc_id` in scope from subscriber entry parsing (line 173-174). One-line change.
- MUST READ: `yapit/gateway/api/v1/ws.py:72-121` — WebSocket handler + pubsub listener. Needs dynamic per-document subscription instead of single per-user subscription at connect time.
- MUST READ: `frontend/src/lib/serverSynthesizer.ts` — `onWSMessage()` and `pendingKey()`. pendingKey needs document_id added (~3 lines).

## Implementation

~15 lines across 3 files:

### 1. `yapit/contracts.py`

Change `get_pubsub_channel` signature to require document_id:

```python
def get_pubsub_channel(user_id: str, document_id: str | uuid.UUID) -> str:
    return f"tts:done:{user_id}:{document_id}"
```

### 2. `yapit/gateway/result_consumer.py:180-181`

Pass `doc_id` (already in scope from line 173-174):

```python
await redis.publish(
    get_pubsub_channel(user_id, doc_id),  # was: get_pubsub_channel(user_id)
    ...
)
```

### 3. `yapit/gateway/api/v1/ws.py`

Refactor `tts_websocket` to subscribe per-document dynamically:

```python
pubsub = redis.pubsub()
subscribed_docs: set[str] = set()

async def ensure_doc_subscribed(document_id: uuid.UUID):
    doc_str = str(document_id)
    if doc_str not in subscribed_docs:
        await pubsub.subscribe(get_pubsub_channel(user.id, doc_str))
        subscribed_docs.add(doc_str)

pubsub_task = asyncio.create_task(_pubsub_listener(ws, pubsub))
```

In the message loop, before `_handle_synthesize`:
```python
await ensure_doc_subscribed(msg.document_id)
```

Simplify `_pubsub_listener` — no longer subscribes, just listens:
```python
async def _pubsub_listener(ws: WebSocket, pubsub):
    async for message in pubsub.listen():
        if message["type"] == "message":
            await ws.send_text(message["data"].decode())
```

Cleanup in `finally` stays the same (`pubsub.close()` unsubscribes all).

### 4. `frontend/src/lib/serverSynthesizer.ts`

Add `documentId` to `pendingKey` — it's part of the identity of a pending synthesis:

```typescript
function pendingKey(blockIdx: number, documentId: string, model: string, voice: string): string {
    return `${documentId}:${blockIdx}:${model}:${voice}`;
}
```

Update all call sites of `pendingKey` (in `synthesize`, `onWSMessage`, and the eviction handler) to pass `documentId`. The `onWSMessage` handler already receives `msg.document_id`.

## Done When

- [ ] `get_pubsub_channel` requires document_id
- [ ] result_consumer publishes to per-document channel
- [ ] WebSocket handler subscribes dynamically per document
- [ ] Frontend `pendingKey` includes documentId
- [ ] Two-tab test: open two documents, play both simultaneously. Verify no cross-contamination (each tab only receives its own blocks).
- [ ] Single-tab test: play a document, switch to another, play that. Verify both work.
- [ ] Stress test multi-user runs no longer show lockstep (validates the fix end-to-end)

## Considered & Rejected

**Client-side-only filtering (frontend + stress test, no server change):** Each client filters `msg.document_id` before acting. Rejected because every future client would need to remember this. The server-side fix makes the contract impossible to misuse at the transport level. The frontend pendingKey fix is semantic correctness, not a routing workaround.

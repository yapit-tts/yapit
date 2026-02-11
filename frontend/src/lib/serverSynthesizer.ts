import type { Synthesizer } from "./synthesizer";
import type { AudioBufferData } from "./playbackEngine";

interface WSSynthesizeRequest {
  type: "synthesize";
  document_id: string;
  block_indices: number[];
  cursor: number;
  model: string;
  voice: string;
  synthesis_mode: "server";
}

interface WSCursorMoved {
  type: "cursor_moved";
  document_id: string;
  cursor: number;
}

export interface WSBlockStatusMessage {
  type: "status";
  document_id: string;
  block_idx: number;
  status: "queued" | "processing" | "cached" | "skipped" | "error";
  audio_url?: string;
  error?: string;
  model_slug?: string;
  voice_slug?: string;
}

export interface WSEvictedMessage {
  type: "evicted";
  document_id: string;
  block_indices: number[];
}

interface PendingRequest {
  resolve: (data: AudioBufferData | null) => void;
  model: string;
  voice: string;
  timer: ReturnType<typeof setTimeout>;
  retryCount: number;
  blockIdx: number;
  documentId: string;
  acknowledged: boolean; // server responded "queued"/"processing" since last timer
}

const MAX_RETRIES = 2;
const RETRY_TIMEOUT_MS = 10_000;

interface ServerSynthesizerDeps {
  sendWS: (msg: WSSynthesizeRequest | WSCursorMoved) => void;
  checkWSConnected: () => boolean;
  fetchAudio: (url: string) => Promise<ArrayBuffer>;
  decodeAudio?: (data: ArrayBuffer) => Promise<AudioBuffer>;
}

/**
 * Server-side TTS synthesizer. Sends synthesis requests over WebSocket,
 * listens for status messages, fetches audio from URLs.
 *
 * Batches per-block synthesize() calls within a microtask into a single
 * WS message. Retries on timeout and recovers pending requests on reconnect.
 */
export function createServerSynthesizer(deps: ServerSynthesizerDeps): Synthesizer & {
  onWSMessage(msg: WSBlockStatusMessage | WSEvictedMessage): void;
  retryAllPending(): void;
} {
  const pending = new Map<string, PendingRequest>();
  let lastError: string | null = null;

  // Batch: collect synthesize calls within a microtask, send as one WS message
  let batchQueue: { blockIdx: number; documentId: string; model: string; voice: string; cursor: number } | null = null;
  let batchIndices: number[] = [];
  let batchScheduled = false;

  function pendingKey(documentId: string, blockIdx: number, model: string, voice: string): string {
    return `${documentId}:${blockIdx}:${model}:${voice}`;
  }

  function sendSynthesizeMsg(documentId: string, blockIndices: number[], cursor: number, model: string, voice: string) {
    deps.sendWS({
      type: "synthesize",
      document_id: documentId,
      block_indices: blockIndices,
      cursor,
      model,
      voice,
      synthesis_mode: "server",
    });
  }

  function createRetryTimer(key: string, req: PendingRequest): ReturnType<typeof setTimeout> {
    return setTimeout(() => {
      if (req.acknowledged) {
        // Server is alive (responded "queued"/"processing"), just slow. Keep waiting.
        req.acknowledged = false;
        req.timer = createRetryTimer(key, req);
      } else if (req.retryCount < MAX_RETRIES) {
        req.retryCount++;
        if (deps.checkWSConnected()) {
          console.warn(`[ServerSynth] Retrying block ${req.blockIdx} (attempt ${req.retryCount})`);
          sendSynthesizeMsg(req.documentId, [req.blockIdx], req.blockIdx, req.model, req.voice);
        }
        // Reset timer regardless — if WS is down, retryAllPending() handles bulk recovery on reconnect
        req.timer = createRetryTimer(key, req);
      } else {
        console.warn(`[ServerSynth] Giving up on block ${req.blockIdx} after ${MAX_RETRIES} retries`);
        pending.delete(key);
        req.resolve(null);
      }
    }, RETRY_TIMEOUT_MS);
  }

  function flushBatch() {
    batchScheduled = false;
    if (!batchQueue || batchIndices.length === 0) return;

    // sendWS queues the message if WS is not connected — it'll be sent on connect
    sendSynthesizeMsg(
      batchQueue.documentId,
      batchIndices,
      batchQueue.cursor,
      batchQueue.model,
      batchQueue.voice,
    );

    batchQueue = null;
    batchIndices = [];
  }

  function synthesize(
    blockIdx: number,
    _text: string,
    documentId: string,
    model: string,
    voice: string,
  ): Promise<AudioBufferData | null> {
    const key = pendingKey(documentId, blockIdx, model, voice);
    const existing = pending.get(key);
    if (existing) return new Promise((resolve) => {
      const origResolve = existing.resolve;
      existing.resolve = (data) => { origResolve(data); resolve(data); };
    });

    return new Promise((resolve) => {
      const req: PendingRequest = {
        resolve,
        model,
        voice,
        timer: 0 as unknown as ReturnType<typeof setTimeout>,
        retryCount: 0,
        blockIdx,
        documentId,
        acknowledged: false,
      };
      req.timer = createRetryTimer(key, req);
      pending.set(key, req);

      // Batch the send — if WS is not connected, sendWS will queue it
      if (!batchScheduled) {
        batchScheduled = true;
        queueMicrotask(flushBatch);
      }
      batchQueue = { blockIdx, documentId, model, voice, cursor: blockIdx };
      batchIndices.push(blockIdx);
    });
  }

  function cancelAll() {
    for (const [key, req] of pending) {
      clearTimeout(req.timer);
      req.resolve(null);
      pending.delete(key);
    }
    batchQueue = null;
    batchIndices = [];
    lastError = null;
  }

  /**
   * Re-send synthesis requests for all pending blocks.
   * Called on WS connect/reconnect. Idempotent — server handles duplicates.
   */
  function retryAllPending() {
    if (pending.size === 0) return;

    // Group by document+model+voice for batch efficiency
    const groups = new Map<string, { documentId: string; model: string; voice: string; indices: number[] }>();
    for (const req of pending.values()) {
      const groupKey = `${req.documentId}:${req.model}:${req.voice}`;
      let group = groups.get(groupKey);
      if (!group) {
        group = { documentId: req.documentId, model: req.model, voice: req.voice, indices: [] };
        groups.set(groupKey, group);
      }
      group.indices.push(req.blockIdx);
    }

    for (const group of groups.values()) {
      sendSynthesizeMsg(group.documentId, group.indices, Math.min(...group.indices), group.model, group.voice);
    }

    // Reset all timers (reconnect resets the clock)
    for (const [key, req] of pending) {
      clearTimeout(req.timer);
      req.retryCount = 0;
      req.timer = createRetryTimer(key, req);
    }

    console.log(`[ServerSynth] Retried ${pending.size} pending blocks on reconnect`);
  }

  function onWSMessage(msg: WSBlockStatusMessage | WSEvictedMessage) {
    if (msg.type === "evicted") {
      for (const idx of msg.block_indices) {
        for (const [key, req] of pending) {
          if (key.startsWith(`${msg.document_id}:${idx}:`)) {
            clearTimeout(req.timer);
            req.resolve(null);
            pending.delete(key);
          }
        }
      }
      return;
    }

    // Status message
    const { block_idx, model_slug, voice_slug } = msg;
    if (!model_slug || !voice_slug) return;

    const key = pendingKey(msg.document_id, block_idx, model_slug, voice_slug);
    const req = pending.get(key);

    if (msg.status === "cached" && msg.audio_url) {
      if (!req) return;
      clearTimeout(req.timer);
      pending.delete(key);

      deps.fetchAudio(msg.audio_url)
        .then(async (arrayBuffer) => {
          if (deps.decodeAudio) {
            const audioBuffer = await deps.decodeAudio(arrayBuffer);
            req.resolve({ buffer: audioBuffer, duration_ms: Math.round(audioBuffer.duration * 1000) });
          } else {
            req.resolve({ rawAudio: arrayBuffer, duration_ms: 0 });
          }
        })
        .catch((err) => {
          console.error(`[ServerSynth] Failed to fetch audio for block ${block_idx}:`, err);
          req.resolve(null);
        });
    } else if (msg.status === "error") {
      lastError = msg.error || "Synthesis error";
      if (req) {
        clearTimeout(req.timer);
        req.resolve(null);
        pending.delete(key);
      }
    } else if (msg.status === "skipped") {
      if (req) {
        clearTimeout(req.timer);
        req.resolve(null);
        pending.delete(key);
      }
    } else if (msg.status === "queued" || msg.status === "processing") {
      if (req) req.acknowledged = true;
    }
  }

  function onCursorMove(documentId: string, cursor: number) {
    if (deps.checkWSConnected()) {
      deps.sendWS({ type: "cursor_moved", document_id: documentId, cursor });
    }
  }

  return {
    synthesize,
    cancelAll,
    onWSMessage,
    onCursorMove,
    retryAllPending,
    getError: () => lastError,
    destroy: cancelAll,
  };
}

export type ServerSynthesizerInstance = ReturnType<typeof createServerSynthesizer>;

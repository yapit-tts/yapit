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
}

const SYNTHESIS_TIMEOUT_MS = 60_000;

interface ServerSynthesizerDeps {
  sendWS: (msg: WSSynthesizeRequest | WSCursorMoved) => void;
  checkWSConnected: () => boolean;
  fetchAudio: (url: string) => Promise<ArrayBuffer>;
  decodeAudio: (data: ArrayBuffer) => Promise<AudioBuffer>;
}

/**
 * Server-side TTS synthesizer. Sends synthesis requests over WebSocket,
 * listens for status messages, fetches audio from URLs.
 *
 * Batches per-block synthesize() calls within a microtask into a single
 * WS message.
 */
export function createServerSynthesizer(deps: ServerSynthesizerDeps): Synthesizer & {
  onWSMessage(msg: WSBlockStatusMessage | WSEvictedMessage): void;
} {
  const pending = new Map<string, PendingRequest>();
  let lastError: string | null = null;

  // Batch: collect synthesize calls within a microtask, send as one WS message
  let batchQueue: { blockIdx: number; documentId: string; model: string; voice: string; cursor: number } | null = null;
  let batchIndices: number[] = [];
  let batchScheduled = false;

  function pendingKey(blockIdx: number, model: string, voice: string): string {
    return `${blockIdx}:${model}:${voice}`;
  }

  function flushBatch() {
    batchScheduled = false;
    if (!batchQueue || batchIndices.length === 0) return;

    deps.sendWS({
      type: "synthesize",
      document_id: batchQueue.documentId,
      block_indices: batchIndices,
      cursor: batchQueue.cursor,
      model: batchQueue.model,
      voice: batchQueue.voice,
      synthesis_mode: "server",
    });

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
    if (!deps.checkWSConnected()) return Promise.resolve(null);

    const key = pendingKey(blockIdx, model, voice);
    const existing = pending.get(key);
    if (existing) return new Promise((resolve) => {
      // Chain onto existing — when original resolves, this one does too
      const origResolve = existing.resolve;
      existing.resolve = (data) => { origResolve(data); resolve(data); };
    });

    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        console.warn(`[ServerSynth] Timeout for block ${blockIdx}`);
        pending.delete(key);
        resolve(null);
      }, SYNTHESIS_TIMEOUT_MS);

      pending.set(key, { resolve, model, voice, timer });

      // Add to batch
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

  function onWSMessage(msg: WSBlockStatusMessage | WSEvictedMessage) {
    if (msg.type === "evicted") {
      for (const idx of msg.block_indices) {
        // Resolve any pending for this block as null (will be re-requested if needed)
        for (const [key, req] of pending) {
          if (key.startsWith(`${idx}:`)) {
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

    const key = pendingKey(block_idx, model_slug, voice_slug);
    const req = pending.get(key);

    if (msg.status === "cached" && msg.audio_url) {
      if (!req) return;
      clearTimeout(req.timer);
      pending.delete(key);

      deps.fetchAudio(msg.audio_url)
        .then((arrayBuffer) => deps.decodeAudio(arrayBuffer))
        .then((audioBuffer) => {
          const durationMs = Math.round(audioBuffer.duration * 1000);
          req.resolve({ buffer: audioBuffer, duration_ms: durationMs });
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
    }
    // queued/processing — no action, just wait
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
    getError: () => lastError,
    destroy: cancelAll,
  };
}

export type ServerSynthesizerInstance = ReturnType<typeof createServerSynthesizer>;

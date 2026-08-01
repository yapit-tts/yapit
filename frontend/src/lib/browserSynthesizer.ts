import type { Synthesizer } from "./synthesizer";
import type { AudioBufferData } from "./playbackEngine";
import type { WorkerMessage, TTSDevice, TTSDtype } from "./browserTTS/types";
import { encodeWavPcm16 } from "./wav";

interface PendingRequest {
  resolve: (data: AudioBufferData | null) => void;
}

/**
 * Browser-side TTS synthesizer using a Web Worker running Kokoro.js.
 * Manages worker lifecycle, cancellation via generation counter,
 * and encodes raw PCM to WAV for the audio element.
 */
export function createBrowserSynthesizer(): Synthesizer & {
  getDevice(): TTSDevice | null;
  getDtype(): TTSDtype | null;
} {
  const pending = new Map<string, PendingRequest>();
  let generation = 0;
  let lastError: string | null = null;
  let device: TTSDevice | null = null;
  let dtype: TTSDtype | null = null;

  const worker = new Worker(
    new URL("./browserTTS/worker.ts", import.meta.url),
    { type: "module" },
  );

  worker.onmessage = (e: MessageEvent<WorkerMessage>) => {
    const msg = e.data;

    switch (msg.type) {
      case "device":
        device = msg.device;
        dtype = msg.dtype;
        break;

      case "audio": {
        const req = pending.get(msg.requestId);
        if (!req) break;
        pending.delete(msg.requestId);
        lastError = null;

        const audio = new Float32Array(msg.audioData);
        const durationMs = Math.round((audio.length / msg.sampleRate) * 1000);
        req.resolve({
          rawAudio: encodeWavPcm16(audio, msg.sampleRate),
          mimeType: "audio/wav",
          duration_ms: durationMs,
        });
        break;
      }

      case "error": {
        const req = pending.get(msg.requestId);
        if (!req) break;
        pending.delete(msg.requestId);

        if (msg.error !== "cancelled") {
          lastError = msg.error;
          console.error(`[BrowserSynth] Worker error:`, msg.error);
        }
        req.resolve(null);
        break;
      }
    }
  };

  worker.onerror = (e) => {
    lastError = e.message || "Worker failed to load";
  };

  function synthesize(
    blockIdx: number,
    text: string,
    _documentId: string,
    _model: string,
    voice: string,
  ): Promise<AudioBufferData | null> {
    const requestId = crypto.randomUUID();

    return new Promise((resolve) => {
      pending.set(requestId, { resolve });

      worker.postMessage({
        type: "synthesize",
        text,
        voice,
        requestId,
        generation,
        blockIdx,
      });
    });
  }

  function cancelAll() {
    generation++;
    worker.postMessage({ type: "cancel", generation });

    for (const [id, req] of pending) {
      req.resolve(null);
      pending.delete(id);
    }
  }

  function destroy() {
    cancelAll();
    worker.terminate();
  }

  return {
    synthesize,
    cancelAll,
    getError: () => lastError,
    isRecoverable: () => true,
    clearError: () => { lastError = null; },
    destroy,
    getDevice: () => device,
    getDtype: () => dtype,
  };
}

export type BrowserSynthesizerInstance = ReturnType<typeof createBrowserSynthesizer>;

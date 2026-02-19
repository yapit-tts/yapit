/**
 * Web Worker for browser-side TTS using Kokoro.js
 *
 * Maintains an explicit FIFO queue processed one at a time.
 * On cancel(generation), the queue is flushed and only the single
 * in-flight synthesis (if any) runs to completion before being discarded.
 */

import { KokoroTTS } from "kokoro-js";
import type { WorkerMessage, MainMessage } from "./types";

let tts: KokoroTTS | null = null;
let loadingPromise: Promise<KokoroTTS> | null = null;
let cancelledGeneration = -1;

const MODEL_ID = "onnx-community/Kokoro-82M-v1.0-ONNX";

type QueueEntry = { text: string; voice: string; requestId: string; generation: number; blockIdx: number };
const queue: QueueEntry[] = [];
let processing = false;

function post(message: WorkerMessage, transfer?: Transferable[]) {
  if (transfer) {
    self.postMessage(message, { transfer });
  } else {
    self.postMessage(message);
  }
}

async function detectWebGPU(): Promise<boolean> {
  if (!navigator.gpu) return false;
  try {
    const adapter = await navigator.gpu.requestAdapter();
    return adapter !== null && !adapter.isFallbackAdapter;
  } catch {
    return false;
  }
}

async function loadModel(): Promise<KokoroTTS> {
  const hasWebGPU = await detectWebGPU();
  const device = hasWebGPU ? "webgpu" : "wasm";
  const dtype = device === "wasm" ? "q8" : "fp32";

  console.log(`[TTS Worker] Device: ${device}, dtype: ${dtype}`);
  post({ type: "device", device, dtype });

  const instance = await KokoroTTS.from_pretrained(MODEL_ID, {
    dtype,
    device,
    progress_callback: (progress) => {
      const pct = "progress" in progress ? (progress.progress ?? 0) : 0;
      post({ type: "progress", progress: pct });
    },
  });

  return instance;
}

async function processQueue() {
  if (processing) return;
  processing = true;

  while (queue.length > 0) {
    const entry = queue.shift()!;
    const { text, voice, requestId, generation, blockIdx } = entry;

    if (generation < cancelledGeneration) {
      post({ type: "error", requestId, error: "cancelled" });
      continue;
    }

    try {
      if (!tts) {
        if (!loadingPromise) {
          console.log("[TTS Worker] Starting model load...");
          const loadStart = performance.now();
          loadingPromise = loadModel();
          loadingPromise.then(() => {
            console.log(`[TTS Worker] Model loaded in ${(performance.now() - loadStart).toFixed(0)}ms`);
          });
        }
        tts = await loadingPromise;

        const voices = Object.keys(tts.voices ?? {});
        post({ type: "ready", voices });
      }

      console.log(`[TTS Worker] Synthesizing block ${blockIdx} (${text.length} chars)...`);
      const genStart = performance.now();
      const audio = await tts.generate(text, { voice: voice as "af_heart" });
      console.log(`[TTS Worker] Block ${blockIdx} done in ${(performance.now() - genStart).toFixed(0)}ms`);

      // Stale check after generation (cursor may have moved mid-synthesis)
      if (generation < cancelledGeneration) {
        post({ type: "error", requestId, error: "cancelled" });
        continue;
      }

      const audioData = audio.data.buffer.slice(0);
      post(
        { type: "audio", requestId, audioData, sampleRate: audio.sampling_rate },
        [audioData]
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      console.error(`[TTS Worker] Error on block ${blockIdx}:`, message);
      post({ type: "error", requestId, error: message });
    }
  }

  processing = false;
}

self.addEventListener("message", (e: MessageEvent<MainMessage>) => {
  const { type } = e.data;

  if (type === "cancel") {
    cancelledGeneration = e.data.generation;
    const flushed = queue.length;
    for (const entry of queue) {
      post({ type: "error", requestId: entry.requestId, error: "cancelled" });
    }
    queue.length = 0;
    if (flushed > 0) {
      console.log(`[TTS Worker] Flushed ${flushed} queued requests (gen ${e.data.generation})`);
    }
    return;
  }

  if (type === "synthesize") {
    queue.push(e.data);
    processQueue();
  }
});

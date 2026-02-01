/**
 * Web Worker for browser-side TTS using Kokoro.js
 *
 * Processes synthesis requests sequentially. Supports cancellation
 * between requests via generation counter — cancel(N) drops all
 * requests with generation <= N.
 */

import { KokoroTTS } from "kokoro-js";
import type { WorkerMessage, MainMessage } from "./types";

let tts: KokoroTTS | null = null;
let loadingPromise: Promise<KokoroTTS> | null = null;
let cancelledGeneration = -1;

const MODEL_ID = "onnx-community/Kokoro-82M-v1.0-ONNX";

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

self.addEventListener("message", async (e: MessageEvent<MainMessage>) => {
  const { type } = e.data;

  if (type === "cancel") {
    cancelledGeneration = e.data.generation;
    return;
  }

  if (type === "synthesize") {
    const { text, voice, requestId, generation } = e.data;

    if (generation < cancelledGeneration) {
      post({ type: "error", requestId, error: "cancelled" });
      return;
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

      console.log(`[TTS Worker] Synthesizing ${text.length} chars...`);
      const genStart = performance.now();
      const audio = await tts.generate(text, { voice: voice as "af_heart" });
      console.log(`[TTS Worker] Generated in ${(performance.now() - genStart).toFixed(0)}ms`);

      // Stale check after generation (voice may have changed mid-synthesis)
      if (generation < cancelledGeneration) {
        post({ type: "error", requestId, error: "cancelled" });
        return;
      }

      const audioData = audio.audio.buffer.slice(0);
      post(
        { type: "audio", requestId, audioData, sampleRate: audio.sampling_rate },
        [audioData]
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      console.error("[TTS Worker] Error:", message);
      post({ type: "error", requestId, error: message });
    }
  }
});

/**
 * Web Worker for browser-side TTS using Kokoro.js
 *
 * Responsibilities:
 * 1. Detect WebGPU vs WASM
 * 2. Load model lazily on first request
 * 3. Process synthesis requests
 * 4. Return audio as transferable ArrayBuffer
 */

import { KokoroTTS } from "kokoro-js";
import type { WorkerMessage, MainMessage } from "./types";

let tts: KokoroTTS | null = null;
let loadingPromise: Promise<KokoroTTS> | null = null;

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
    return adapter !== null;
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
      // Progress info varies by stage - extract progress percentage when available
      const pct = "progress" in progress ? (progress.progress ?? 0) : 0;
      post({ type: "progress", progress: pct });
    },
  });

  return instance;
}

self.addEventListener("message", async (e: MessageEvent<MainMessage>) => {
  const { type } = e.data;

  if (type === "synthesize") {
    const { text, voice, requestId } = e.data;
    const synthStart = performance.now();

    try {
      // Lazy load model on first synthesis
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

        // Get available voices from the model
        const voices = Object.keys(tts.voices ?? {});
        post({ type: "ready", voices });
      }

      // Synthesize audio - voice type is checked at runtime
      console.log(`[TTS Worker] Synthesizing ${text.length} chars...`);
      const genStart = performance.now();
      const audio = await tts.generate(text, { voice: voice as "af_heart" });
      console.log(`[TTS Worker] Generated in ${(performance.now() - genStart).toFixed(0)}ms`);

      // Transfer audio data (zero-copy)
      // RawAudio has .audio (Float32Array) and .sampling_rate
      const audioData = audio.audio.buffer.slice(0);
      console.log(`[TTS Worker] Total request time: ${(performance.now() - synthStart).toFixed(0)}ms`);
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

import { useRef, useState, useEffect, useCallback, useMemo } from "react";
import type { WorkerMessage, TTSDevice, TTSDtype } from "./types";

interface BrowserTTSState {
  isLoading: boolean;
  loadingProgress: number;
  device: TTSDevice | null;
  dtype: TTSDtype | null;
  voices: string[];
  isReady: boolean;
  error: string | null;
}

interface SynthesisRequest {
  onComplete: (audio: Float32Array, sampleRate: number) => void;
  onError?: (error: Error) => void;
}

const DEFAULT_VOICE = "af_heart";

export function useBrowserTTS() {
  const workerRef = useRef<Worker | null>(null);
  const pendingRequestsRef = useRef<Map<string, SynthesisRequest>>(new Map());
  const isReadyRef = useRef(false);
  const [state, setState] = useState<BrowserTTSState>({
    isLoading: false,
    loadingProgress: 0,
    device: null,
    dtype: null,
    voices: [],
    isReady: false,
    error: null,
  });

  // Initialize worker on mount (singleton pattern - worker persists across renders)
  useEffect(() => {
    workerRef.current = new Worker(
      new URL("./worker.ts", import.meta.url),
      { type: "module" }
    );

    workerRef.current.onmessage = (e: MessageEvent<WorkerMessage>) => {
      const message = e.data;

      switch (message.type) {
        case "device":
          setState((s) => ({
            ...s,
            device: message.device,
            dtype: message.dtype,
            isLoading: true,
          }));
          break;

        case "progress":
          setState((s) => ({ ...s, loadingProgress: message.progress }));
          break;

        case "ready":
          isReadyRef.current = true;
          setState((s) => ({
            ...s,
            isReady: true,
            isLoading: false,
            voices: message.voices,
          }));
          break;

        case "audio": {
          const request = pendingRequestsRef.current.get(message.requestId);
          if (request) {
            const audio = new Float32Array(message.audioData);
            request.onComplete(audio, message.sampleRate);
            pendingRequestsRef.current.delete(message.requestId);
          }
          break;
        }

        case "error": {
          const request = pendingRequestsRef.current.get(message.requestId);
          if (request?.onError) {
            request.onError(new Error(message.error));
          }
          pendingRequestsRef.current.delete(message.requestId);
          setState((s) => ({ ...s, error: message.error }));
          break;
        }
      }
    };

    workerRef.current.onerror = (e) => {
      setState((s) => ({ ...s, error: e.message, isLoading: false }));
    };

    return () => {
      workerRef.current?.terminate();
      workerRef.current = null;
    };
  }, []);

  /**
   * Synthesize text to audio using the browser TTS worker
   * Returns a promise that resolves with the audio data
   */
  const synthesize = useCallback(
    (
      text: string,
      options: { voice?: string } = {}
    ): Promise<{ audio: Float32Array; sampleRate: number }> => {
      return new Promise((resolve, reject) => {
        if (!workerRef.current) {
          reject(new Error("TTS worker not initialized"));
          return;
        }

        const requestId = crypto.randomUUID();

        pendingRequestsRef.current.set(requestId, {
          onComplete: (audio, sampleRate) => resolve({ audio, sampleRate }),
          onError: reject,
        });

        // Set loading state if this is the first request (model will load)
        if (!isReadyRef.current) {
          setState((s) => ({ ...s, isLoading: true }));
        }

        workerRef.current.postMessage({
          type: "synthesize",
          text,
          voice: options.voice ?? DEFAULT_VOICE,
          requestId,
        });
      });
    },
    []
  );

  return useMemo(
    () => ({
      ...state,
      synthesize,
    }),
    [state, synthesize]
  );
}

import { useCallback, useEffect, useRef, useSyncExternalStore } from "react";
import { useApi } from "@/api";
import { AudioPlayer } from "@/lib/audio";
import {
  createPlaybackEngine,
  type Block,
  type PlaybackEngine,
  type PlaybackSnapshot,
} from "@/lib/playbackEngine";
import { isServerSideModel, type VoiceSelection } from "@/lib/voiceSelection";
import type { Section } from "@/lib/sectionIndex";
import { createServerSynthesizer, type ServerSynthesizerInstance, type WSBlockStatusMessage, type WSEvictedMessage } from "@/lib/serverSynthesizer";
import { createBrowserSynthesizer, type BrowserSynthesizerInstance } from "@/lib/browserSynthesizer";
import { useTTSWebSocket, type WSMessage } from "./useTTSWebSocket";

export type { PlaybackSnapshot, Block };

export interface UsePlaybackEngineReturn {
  snapshot: PlaybackSnapshot;
  engine: PlaybackEngine;
  ws: {
    isConnected: boolean;
    isReconnecting: boolean;
    connectionError: string | null;
  };
  serverTTS: {
    error: string | null;
  };
  browserTTS: {
    error: string | null;
    device: "webgpu" | "wasm" | null;
    loading: boolean;
    loadingProgress: number;
  };
}

export function usePlaybackEngine(
  documentId: string | undefined,
  blocks: Block[],
  voiceSelection: VoiceSelection,
  sections: Section[],
  skippedSections: Set<string>,
): UsePlaybackEngineReturn {
  const { api } = useApi();

  const apiRef = useRef(api);
  apiRef.current = api;

  // AudioContext needed for decoding (decodeAudioData, createBuffer).
  // AudioPlayer plays directly through HTMLAudioElement (no Web Audio routing).
  const audioContextRef = useRef<AudioContext | null>(null);
  const audioPlayerRef = useRef<AudioPlayer | null>(null);
  const engineRef = useRef<PlaybackEngine | null>(null);
  const serverSynthRef = useRef<ServerSynthesizerInstance | null>(null);
  const browserSynthRef = useRef<BrowserSynthesizerInstance | null>(null);

  if (!audioContextRef.current) {
    audioContextRef.current = new AudioContext();
  }
  const audioContext = audioContextRef.current;

  if (!audioPlayerRef.current) {
    audioPlayerRef.current = new AudioPlayer();
  }

  // WS message handler — forwards to server synthesizer
  const handleWSMessage = useCallback((data: WSMessage) => {
    if (!serverSynthRef.current) return;
    if (data.type === "status") {
      serverSynthRef.current.onWSMessage(data as unknown as WSBlockStatusMessage);
    } else if (data.type === "evicted") {
      serverSynthRef.current.onWSMessage(data as unknown as WSEvictedMessage);
    } else if (data.type === "error") {
      console.error("[TTS WS] Server error:", (data as { error?: string }).error);
    }
  }, []);

  // On WS connect/reconnect: retry all pending synthesis requests
  const handleWSConnect = useCallback(() => {
    serverSynthRef.current?.retryAllPending();
  }, []);

  const ttsWS = useTTSWebSocket(handleWSMessage, handleWSConnect);

  // Stable refs for WS deps
  const sendWSRef = useRef(ttsWS.send);
  sendWSRef.current = ttsWS.send;
  const checkConnectedRef = useRef(ttsWS.checkConnected);
  checkConnectedRef.current = ttsWS.checkConnected;

  // Create synthesizers and engine once
  if (!serverSynthRef.current) {
    serverSynthRef.current = createServerSynthesizer({
      sendWS: (msg) => sendWSRef.current(msg),
      checkWSConnected: () => checkConnectedRef.current(),
      fetchAudio: async (url: string) => {
        const response = await apiRef.current.get(url, { responseType: "arraybuffer" });
        return response.data;
      },
      decodeAudio: (data: ArrayBuffer) => audioContext.decodeAudioData(data.slice(0)),
    });
  }

  if (!browserSynthRef.current) {
    browserSynthRef.current = createBrowserSynthesizer({ audioContext });
  }

  const originalPlayRef = useRef<(() => void) | null>(null);

  if (!engineRef.current) {
    engineRef.current = createPlaybackEngine({
      audioPlayer: audioPlayerRef.current,
      synthesizer: serverSynthRef.current,
    });
  }
  const engine = engineRef.current;

  // Capture original play BEFORE any wrapping, then wrap exactly once
  if (!originalPlayRef.current) {
    originalPlayRef.current = engine.play;
    const audioPlayer = audioPlayerRef.current!;
    (engine as { play: () => void }).play = () => {
      // Both fire synchronously in the user gesture context (tap/click handler).
      // unlock() registers the HTMLAudioElement with the browser for programmatic play.
      // resume() unlocks AudioContext for decodeAudioData in synthesizers.
      audioPlayer.unlock();
      if (audioContext.state === "suspended") {
        audioContext.resume().catch(() => {});
      }
      originalPlayRef.current!();
    };
  }

  // Sync document into engine
  useEffect(() => {
    if (documentId && blocks.length > 0) {
      engine.setDocument(documentId, blocks);
    }
  }, [documentId, blocks, engine]);

  // Sync voice selection — also swap synthesizer when model type changes
  useEffect(() => {
    const synth = isServerSideModel(voiceSelection.model)
      ? serverSynthRef.current!
      : browserSynthRef.current!;
    engine.setSynthesizer(synth);
    engine.setVoice(voiceSelection.model, voiceSelection.voiceSlug);
  }, [voiceSelection.model, voiceSelection.voiceSlug, engine]);

  // Sync sections
  useEffect(() => {
    engine.setSections(sections, skippedSections);
  }, [sections, skippedSections, engine]);

  // Keep AudioContext alive during playback for ongoing synthesis/decoding.
  // If suspended (mobile app switch, phone call), decodeAudioData may fail.
  useEffect(() => {
    const handler = () => {
      const engineStatus = engine.getSnapshot().status;
      console.log(`[AudioContext] State changed to "${audioContext.state}" (engine: ${engineStatus})`);
      if (audioContext.state === "suspended" && (engineStatus === "playing" || engineStatus === "buffering")) {
        console.warn("[AudioContext] Suspended while engine active — resuming for synthesis...");
        audioContext.resume().catch(() => {});
      }
    };
    audioContext.addEventListener("statechange", handler);
    return () => audioContext.removeEventListener("statechange", handler);
  }, [audioContext, engine]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      engine.destroy();
      browserSynthRef.current?.destroy();
      audioContext.close();
    };
  }, [engine, audioContext]);

  const snapshot = useSyncExternalStore(engine.subscribe, engine.getSnapshot);

  const browserSynth = browserSynthRef.current!;
  return {
    snapshot,
    engine,
    ws: {
      isConnected: ttsWS.isConnected,
      isReconnecting: ttsWS.isReconnecting,
      connectionError: ttsWS.connectionError,
    },
    serverTTS: {
      error: serverSynthRef.current!.getError(),
    },
    browserTTS: {
      error: browserSynth.getError(),
      device: browserSynth.getDevice(),
      loading: browserSynth.isLoading(),
      loadingProgress: browserSynth.getLoadingProgress(),
    },
  };
}

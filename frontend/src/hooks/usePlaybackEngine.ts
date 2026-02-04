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
  gainNode: GainNode | null;
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

  // Create AudioContext and AudioPlayer once
  const audioContextRef = useRef<AudioContext | null>(null);
  const gainNodeRef = useRef<GainNode | null>(null);
  const audioPlayerRef = useRef<AudioPlayer | null>(null);
  const engineRef = useRef<PlaybackEngine | null>(null);
  const serverSynthRef = useRef<ServerSynthesizerInstance | null>(null);
  const browserSynthRef = useRef<BrowserSynthesizerInstance | null>(null);

  if (!audioContextRef.current) {
    audioContextRef.current = new AudioContext();
  }
  const audioContext = audioContextRef.current;

  if (!audioPlayerRef.current) {
    gainNodeRef.current = audioContext.createGain();
    gainNodeRef.current.connect(audioContext.destination);
    audioPlayerRef.current = new AudioPlayer({ audioContext, gainNode: gainNodeRef.current });
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

  const ttsWS = useTTSWebSocket(handleWSMessage);

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

  if (!engineRef.current) {
    engineRef.current = createPlaybackEngine({
      audioPlayer: audioPlayerRef.current,
      synthesizer: serverSynthRef.current,
    });
  }
  const engine = engineRef.current;

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

  // Resume AudioContext on user interaction (browser autoplay policy)
  const originalPlay = engine.play;
  const playWithResume = useCallback(async () => {
    if (audioContext.state === "suspended") {
      console.warn("[AudioContext] Resuming from suspended state on play()");
      await audioContext.resume();
    }
    originalPlay();
  }, [audioContext, originalPlay]);
  (engine as { play: () => void }).play = playWithResume as () => void;

  // Detect AudioContext suspension (mobile app switch, phone call, etc.)
  // If the context gets suspended while engine thinks it's playing, audio silently stops
  // and the ended event never fires — leaving playback stuck.
  useEffect(() => {
    const handler = () => {
      const engineStatus = engine.getSnapshot().status;
      console.log(`[AudioContext] State changed to "${audioContext.state}" (engine: ${engineStatus})`);
      if (audioContext.state === "suspended" && (engineStatus === "playing" || engineStatus === "buffering")) {
        console.warn("[AudioContext] Suspended while engine active — audio may be stuck. Attempting resume...");
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
    gainNode: gainNodeRef.current,
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

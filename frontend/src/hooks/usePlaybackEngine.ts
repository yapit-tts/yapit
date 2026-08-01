import { useCallback, useEffect, useMemo, useRef } from "react";
import { useApi } from "@/api";
import { AudioPlayer } from "@/lib/audio";
import {
  createPlaybackEngine,
  type Block,
  type PlaybackEngine,
} from "@/lib/playbackEngine";
import { isServerSideModel, type VoiceSelection } from "@/lib/voiceSelection";
import type { Section } from "@/lib/sectionIndex";
import { createServerSynthesizer, type ServerSynthesizerInstance, type WSBlockStatusMessage, type WSEvictedMessage } from "@/lib/serverSynthesizer";
import { createBrowserSynthesizer, type BrowserSynthesizerInstance } from "@/lib/browserSynthesizer";
import { useTTSWebSocket, type WSMessage } from "./useTTSWebSocket";

export type { Block };

export interface UsePlaybackEngineReturn {
  engine: PlaybackEngine;
  ws: {
    isConnected: boolean;
    isReconnecting: boolean;
    connectionError: string | null;
  };
  getServerTTSStatus: () => { error: string | null; recoverable: boolean };
  getBrowserTTSStatus: () => {
    error: string | null;
    device: "webgpu" | "wasm" | null;
  };
}

export function usePlaybackEngine(
  documentId: string | undefined,
  blocks: Block[],
  voiceSelection: VoiceSelection,
  sections: Section[],
  expandedSections: Set<string>,
): UsePlaybackEngineReturn {
  const { api } = useApi();

  const apiRef = useRef(api);
  apiRef.current = api;

  const audioPlayerRef = useRef<AudioPlayer | null>(null);
  const engineRef = useRef<PlaybackEngine | null>(null);
  const serverSynthRef = useRef<ServerSynthesizerInstance | null>(null);
  const browserSynthRef = useRef<BrowserSynthesizerInstance | null>(null);

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
    });
  }

  // Created on first use: constructing it spawns the Kokoro worker, which pulls
  // ~1.8MB of JS into a second isolate that server-side voices never touch.
  const getBrowserSynth = useCallback(() => {
    if (!browserSynthRef.current) {
      browserSynthRef.current = createBrowserSynthesizer();
    }
    return browserSynthRef.current;
  }, []);

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
      // Fires synchronously in the user gesture context (tap/click handler):
      // unlock() registers the HTMLAudioElement with the browser for programmatic play.
      audioPlayer.unlock();
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
      : getBrowserSynth();
    engine.setSynthesizer(synth);
    engine.setVoice(voiceSelection.model, voiceSelection.voiceSlug);
  }, [voiceSelection.model, voiceSelection.voiceSlug, engine, getBrowserSynth]);

  // Sync sections — derive collapsed (skipped) set from expandedSections
  const collapsedSections = useMemo(
    () => new Set(sections.filter(s => !expandedSections.has(s.id)).map(s => s.id)),
    [sections, expandedSections],
  );
  useEffect(() => {
    engine.setSections(sections, collapsedSections);
  }, [sections, collapsedSections, engine]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      engine.destroy();
      browserSynthRef.current?.destroy();
    };
  }, [engine]);

  // Getter functions for TTS status — called by the overlay during its render
  // to get fresh values without requiring a shell re-render.
  const getServerTTSStatus = useCallback(() => ({
    error: serverSynthRef.current!.getError(),
    recoverable: serverSynthRef.current!.isRecoverable(),
  }), []);

  const getBrowserTTSStatus = useCallback(() => {
    const synth = browserSynthRef.current;
    if (!synth) return { error: null, device: null };
    return { error: synth.getError(), device: synth.getDevice() };
  }, []);

  return {
    engine,
    ws: {
      isConnected: ttsWS.isConnected,
      isReconnecting: ttsWS.isReconnecting,
      connectionError: ttsWS.connectionError,
    },
    getServerTTSStatus,
    getBrowserTTSStatus,
  };
}

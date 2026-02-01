import { useCallback, useEffect, useRef, useSyncExternalStore } from "react";
import { useApi } from "@/api";
import { AudioPlayer } from "@/lib/audio";
import { useBrowserTTS } from "@/lib/browserTTS";
import {
  createPlaybackEngine,
  type Block,
  type PlaybackEngine,
  type PlaybackSnapshot,
  type WSBlockStatusMessage,
  type WSEvictedMessage,
} from "@/lib/playbackEngine";
import { isServerSideModel, type VoiceSelection } from "@/lib/voiceSelection";
import type { Section } from "@/lib/sectionIndex";
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
}

export function usePlaybackEngine(
  documentId: string | undefined,
  blocks: Block[],
  voiceSelection: VoiceSelection,
  sections: Section[],
  skippedSections: Set<string>,
): UsePlaybackEngineReturn {
  const { api } = useApi();
  const browserTTS = useBrowserTTS();

  // Stable refs for engine deps that shouldn't trigger re-creation
  const apiRef = useRef(api);
  apiRef.current = api;

  // Create AudioContext and AudioPlayer once
  const audioContextRef = useRef<AudioContext | null>(null);
  const gainNodeRef = useRef<GainNode | null>(null);
  const audioPlayerRef = useRef<AudioPlayer | null>(null);
  const engineRef = useRef<PlaybackEngine | null>(null);

  if (!audioContextRef.current) {
    audioContextRef.current = new AudioContext();
  }
  const audioContext = audioContextRef.current;

  if (!audioPlayerRef.current) {
    gainNodeRef.current = audioContext.createGain();
    gainNodeRef.current.connect(audioContext.destination);
    audioPlayerRef.current = new AudioPlayer({ audioContext, gainNode: gainNodeRef.current });
  }

  // Engine message handler for WS — forwards to engine
  const handleWSMessage = useCallback((data: WSMessage) => {
    if (!engineRef.current) return;
    if (data.type === "status") {
      engineRef.current.onBlockStatus(data as unknown as WSBlockStatusMessage);
    } else if (data.type === "evicted") {
      engineRef.current.onBlockEvicted(data as unknown as WSEvictedMessage);
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

  // Create engine once
  if (!engineRef.current) {
    engineRef.current = createPlaybackEngine({
      audioPlayer: audioPlayerRef.current,
      decodeAudio: (data: ArrayBuffer) => audioContext.decodeAudioData(data.slice(0)),
      fetchAudio: async (url: string) => {
        const response = await apiRef.current.get(url, { responseType: "arraybuffer" });
        return response.data;
      },
      sendWS: (msg) => sendWSRef.current(msg),
      checkWSConnected: () => checkConnectedRef.current(),
    });
  }
  const engine = engineRef.current;

  const browserInflightRef = useRef(new Set<number>());

  // Sync document into engine
  useEffect(() => {
    if (documentId && blocks.length > 0) {
      engine.setDocument(documentId, blocks);
    }
  }, [documentId, blocks, engine]);

  // Sync voice selection
  useEffect(() => {
    engine.setVoice(voiceSelection.model, voiceSelection.voiceSlug);
    browserInflightRef.current.clear();
  }, [voiceSelection.model, voiceSelection.voiceSlug, engine]);

  // Sync sections
  useEffect(() => {
    engine.setSections(sections, skippedSections);
  }, [sections, skippedSections, engine]);

  // Resume AudioContext on user interaction (browser autoplay policy)
  const originalPlay = engine.play;
  const playWithResume = useCallback(async () => {
    if (audioContext.state === "suspended") {
      await audioContext.resume();
    }
    originalPlay();
  }, [audioContext, originalPlay]);
  // Patch play to handle AudioContext resume
  (engine as { play: () => void }).play = playWithResume as () => void;

  // Drive browser-side TTS synthesis for pending blocks
  const browserTTSRef = useRef(browserTTS);
  browserTTSRef.current = browserTTS;

  useEffect(() => {
    if (isServerSideModel(voiceSelection.model)) return;

    const inflight = browserInflightRef.current;
    const pending = engine.getPendingBrowserBlocks();
    for (const blockIdx of pending) {
      if (inflight.has(blockIdx)) continue;
      const block = blocks[blockIdx];
      if (!block) continue;

      inflight.add(blockIdx);
      browserTTSRef.current.synthesize(block.text, { voice: voiceSelection.voiceSlug })
        .then(({ audio, sampleRate }) => {
          const audioBuffer = audioContext.createBuffer(1, audio.length, sampleRate);
          audioBuffer.getChannelData(0).set(audio);
          const durationMs = Math.round((audio.length / sampleRate) * 1000);
          engine.onBrowserAudio(blockIdx, audioBuffer, durationMs);
        })
        .catch((err) => {
          console.error(`[Browser TTS] Synthesis failed for block ${blockIdx}:`, err);
          engine.cancelBrowserBlock(blockIdx);
        })
        .finally(() => {
          inflight.delete(blockIdx);
        });
    }
  });

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      engine.destroy();
      audioContext.close();
    };
  }, [engine, audioContext]);

  // Subscribe to engine snapshots
  const snapshot = useSyncExternalStore(engine.subscribe, engine.getSnapshot);

  return {
    snapshot,
    engine,
    gainNode: gainNodeRef.current,
    ws: {
      isConnected: ttsWS.isConnected,
      isReconnecting: ttsWS.isReconnecting,
      connectionError: ttsWS.connectionError,
    },
  };
}

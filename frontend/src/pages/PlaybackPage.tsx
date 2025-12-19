import { SoundControl } from '@/components/soundControl';
import { StructuredDocumentView } from '@/components/structuredDocument';
import { useParams, useLocation } from "react-router";
import { useRef, useState, useEffect, useCallback } from "react";
import { useApi } from '@/api';
import { Loader2 } from "lucide-react";
import { AudioPlayer } from '@/lib/audio';
import { useBrowserTTS } from '@/lib/browserTTS';
import { type VoiceSelection, getVoiceSelection } from '@/lib/voiceSelection';
import { useSettings } from '@/hooks/useSettings';

// Playback position persistence
const POSITION_KEY_PREFIX = "yapit_playback_position_";

interface PlaybackPosition {
  block: number;
  progressMs: number;
}

function getPlaybackPosition(documentId: string): PlaybackPosition | null {
  try {
    const stored = localStorage.getItem(POSITION_KEY_PREFIX + documentId);
    if (stored) return JSON.parse(stored);
  } catch {
    // Ignore parse errors
  }
  return null;
}

function setPlaybackPosition(documentId: string, position: PlaybackPosition): void {
  localStorage.setItem(POSITION_KEY_PREFIX + documentId, JSON.stringify(position));
}

interface Block {
  id: number;
  idx: number;
  text: string;
  est_duration_ms: number;
}

interface DocumentResponse {
  id: string;
  title: string | null;
  original_text: string;
  filtered_text: string | null;
  structured_content: string | null;
}

interface AudioBufferData {
  buffer: AudioBuffer;
  duration_ms: number;
}

// Convert PCM Int16 bytes to Float32Array for Web Audio API
function pcmToFloat32(pcmData: ArrayBuffer): Float32Array {
  const int16View = new Int16Array(pcmData);
  const float32 = new Float32Array(int16View.length);
  for (let i = 0; i < int16View.length; i++) {
    float32[i] = int16View[i] / 32768; // Normalize Int16 to [-1, 1]
  }
  return float32;
}

const PlaybackPage = () => {
  const { documentId } = useParams<{ documentId: string }>();
  const { state } = useLocation();
  const initialTitle: string | undefined = state?.documentTitle;

  const { api, isAuthReady } = useApi();
  const browserTTS = useBrowserTTS();
  const { settings } = useSettings();

  // Document data fetched from API
  const [document, setDocument] = useState<DocumentResponse | null>(null);
  const [documentBlocks, setDocumentBlocks] = useState<Block[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Derived state
  const documentTitle = document?.title ?? initialTitle;
  const structuredContent = document?.structured_content ?? null;
  const fallbackContent = document?.filtered_text ?? document?.original_text ?? "";
  const numberOfBlocks = documentBlocks.length;
  const estimated_ms = documentBlocks.reduce((sum, b) => sum + (b.est_duration_ms || 0), 0);

  // Sound control variables
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const isPlayingRef = useRef<boolean>(false); // Ref to track current state for async callbacks
  const [volume, setVolume] = useState<number>(50);
  const [playbackSpeed, setPlaybackSpeed] = useState<number>(settings.defaultSpeed);
  const [isSynthesizing, setIsSynthesizing] = useState<boolean>(false);
  const [voiceSelection, setVoiceSelection] = useState<VoiceSelection>(getVoiceSelection);

  // Audio setup variables
  const audioContextRef = useRef<AudioContext | null>(null);
  const gainNodeRef = useRef<GainNode | null>(null);
  const audioPlayerRef = useRef<AudioPlayer | null>(null);
  const [currentBlock, setCurrentBlock] = useState<number>(-1);
	const audioBuffersRef = useRef<Map<number, AudioBufferData>>(new Map());
	const synthesizingRef = useRef<Map<number, Promise<AudioBufferData | null>>>(new Map()); // Track in-progress synthesis promises
	const [audioProgress, setAudioProgress] = useState<number>(0);
	const blockStartTimeRef = useRef<number>(0);
	const [actualTotalDuration, setActualTotalDuration] = useState<number>(0);
	const durationCorrectionsRef = useRef<Map<number, number>>(new Map());
	const initialTotalEstimateRef = useRef<number>(0);
  const currentBlockDurationRef = useRef<number>(0);

  // Fetch document and blocks on mount (wait for auth to be ready)
  useEffect(() => {
    if (!isAuthReady) return;

    if (!documentId) {
      setError("No document ID provided");
      setIsLoading(false);
      return;
    }

    const fetchData = async () => {
      try {
        const [docResponse, blocksResponse] = await Promise.all([
          api.get<DocumentResponse>(`/v1/documents/${documentId}`),
          api.get<Block[]>(`/v1/documents/${documentId}/blocks`),
        ]);
        setDocument(docResponse.data);
        setDocumentBlocks(blocksResponse.data);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to fetch document");
      } finally {
        setIsLoading(false);
      }
    };

    fetchData();
  }, [documentId, api, isAuthReady]);

  // Initialize the AudioContext, GainNode, and AudioPlayer
  useEffect(() => {
    // Create new AudioContext if none exists or previous one was closed
    if (!audioContextRef.current || audioContextRef.current.state === 'closed') {
      audioContextRef.current = new AudioContext();
      gainNodeRef.current = audioContextRef.current.createGain();
      gainNodeRef.current.connect(audioContextRef.current.destination);
      gainNodeRef.current.gain.value = volume / 100;
    }

    // Create AudioPlayer if needed (uses browser native preservesPitch)
    if (!audioPlayerRef.current && audioContextRef.current && gainNodeRef.current) {
      audioPlayerRef.current = new AudioPlayer({
        audioContext: audioContextRef.current,
        gainNode: gainNodeRef.current,
        onProgress: (percentPlayed, blockDurationMs) => {
          // Calculate total progress: previous blocks + current block position
          const blockProgress = (percentPlayed / 100) * blockDurationMs;
          const totalProgress = blockStartTimeRef.current + blockProgress;
          setAudioProgress(totalProgress);
        },
      });
      audioPlayerRef.current.setTempo(playbackSpeed);
    }
  }, [volume, playbackSpeed]);

  // Reset playback state when switching documents or unmounting
  useEffect(() => {
    return () => {
      audioPlayerRef.current?.stop();
      audioContextRef.current?.suspend(); // Immediately cut off any buffered audio
      setIsPlaying(false);
      setCurrentBlock(-1);
      setAudioProgress(0);
      blockStartTimeRef.current = 0;
    };
  }, [documentId]);

  // Calculate initial total duration from block estimates
  useEffect(() => {
    if (documentBlocks && documentBlocks.length > 0) {
      let totalEstimate = 0;
      for (const block of documentBlocks) {
        totalEstimate += block.est_duration_ms || 0;
      }
      initialTotalEstimateRef.current = totalEstimate;
      setActualTotalDuration(totalEstimate);
    } else if (estimated_ms) {
      initialTotalEstimateRef.current = estimated_ms;
      setActualTotalDuration(estimated_ms);
    }
  }, [documentBlocks, estimated_ms]);

  // Restore playback position from localStorage when document loads
  useEffect(() => {
    if (!documentId || documentBlocks.length === 0) return;

    const saved = getPlaybackPosition(documentId);
    if (saved && saved.block >= 0 && saved.block < documentBlocks.length) {
      setCurrentBlock(saved.block);
      setAudioProgress(saved.progressMs);
      blockStartTimeRef.current = saved.progressMs;

      // Scroll to restored block after React renders the blocks
      if (settings.scrollOnRestore) {
        setTimeout(() => {
          const blockElement = window.document.querySelector(
            `[data-audio-block-idx="${saved.block}"]`
          );
          if (blockElement) {
            blockElement.scrollIntoView({ behavior: "smooth", block: "center" });
          }
        }, 100);
      }
    }
  }, [documentId, documentBlocks.length, settings.scrollOnRestore]);

  // Ref to track documentId for position saving (avoids saving old position to new doc on navigation)
  const documentIdRef = useRef(documentId);
  documentIdRef.current = documentId;

  // Save playback position when currentBlock changes
  // Uses ref for documentId so navigating to a new doc doesn't save old position to new doc's key
  useEffect(() => {
    if (!documentIdRef.current || currentBlock < 0) return;

    setPlaybackPosition(documentIdRef.current, {
      block: currentBlock,
      progressMs: blockStartTimeRef.current,
    });
  }, [currentBlock]); // Only depend on currentBlock - documentId comes from ref

  // Live scroll tracking - keep current block visible during playback
  useEffect(() => {
    // Only scroll during active playback (not on restore or manual click)
    if (currentBlock < 0 || !isPlayingRef.current || !settings.liveScrollTracking) return;

    const blockElement = window.document.querySelector(
      `[data-audio-block-idx="${currentBlock}"]`
    );
    if (blockElement) {
      blockElement.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [currentBlock, settings.liveScrollTracking]);

  // Refs for keyboard handler to avoid stale closures
  const handlePlayRef = useRef<() => void>(() => {});
  const handlePauseRef = useRef<() => void>(() => {});

  // Keyboard handler for spacebar play/pause (uses refs to avoid stale closures)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Only handle spacebar when not focused on an input
      if (e.code === "Space" && !["INPUT", "TEXTAREA", "SELECT"].includes((e.target as HTMLElement).tagName)) {
        e.preventDefault(); // Prevent page scroll
        if (isPlayingRef.current) {
          handlePauseRef.current();
        } else {
          handlePlayRef.current();
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []); // Empty deps - uses refs

  // Update gain node value when volume changes
  useEffect(() => {
    if (gainNodeRef.current) {
      gainNodeRef.current.gain.value = volume / 100;
    }
  }, [volume]);

  // Update playback speed in real-time (pitch-preserving)
  useEffect(() => {
    if (audioPlayerRef.current) {
      audioPlayerRef.current.setTempo(playbackSpeed);
    }
  }, [playbackSpeed]);

  // When voice changes: clear cache and mark for restart if playing
  const voiceSelectionRef = useRef(voiceSelection);
  const pendingVoiceChangeRef = useRef(false);
  useEffect(() => {
    const voiceChanged = voiceSelectionRef.current.model !== voiceSelection.model ||
                         voiceSelectionRef.current.voiceSlug !== voiceSelection.voiceSlug;
    voiceSelectionRef.current = voiceSelection;

    if (!voiceChanged) return;

    // Clear all cached audio (synthesized with old voice)
    audioBuffersRef.current.clear();
    synthesizingRef.current.clear();
    durationCorrectionsRef.current.clear();

    // If we were playing, mark that we need to restart after synthesizeBlock is recreated
    if (isPlayingRef.current && currentBlock >= 0) {
      audioPlayerRef.current?.stop();
      setIsSynthesizing(true);
      pendingVoiceChangeRef.current = true;
    }
  }, [voiceSelection, currentBlock]);


  const synthesizeBlock = useCallback(async (blockId: number): Promise<AudioBufferData | null> => {
    // Check if already cached
    const cached = audioBuffersRef.current.get(blockId);
    if (cached) {
      console.log(`[Playback] Block ${blockId} already cached, returning`);
      return cached;
    }

    // Check if synthesis already in progress - return the existing promise
    const existingPromise = synthesizingRef.current.get(blockId);
    if (existingPromise) {
      console.log(`[Playback] Block ${blockId} already synthesizing, awaiting existing promise`);
      return existingPromise;
    }

    // Find the block to get its text
    const block = documentBlocks.find(b => b.id === blockId);
    if (!block) {
      console.error("[Playback] Block not found:", blockId);
      return null;
    }

    if (!audioContextRef.current) {
      return null;
    }

    // Create the synthesis promise
    const synthesisPromise = (async (): Promise<AudioBufferData | null> => {
      try {
        console.log(`[Playback] Starting synthesis for block ${blockId} (idx ${block.idx}, ${block.text.length} chars)`);
        const startTime = performance.now();

        let floatData: Float32Array;
        let sampleRate: number;
        let durationMs: number;

        if (voiceSelection.model === "higgs" || voiceSelection.model === "kokoro-server") {
          // Server-side synthesis via API
          const modelSlug = voiceSelection.model === "higgs" ? "higgs-native" : "kokoro-cpu";
          const response = await api.post(
            `/v1/documents/${documentId}/blocks/${blockId}/synthesize/models/${modelSlug}/voices/${voiceSelection.voiceSlug}`,
            null,
            { responseType: "arraybuffer" }
          );

          sampleRate = parseInt(response.headers["x-sample-rate"] || "24000", 10);
          durationMs = parseInt(response.headers["x-duration-ms"] || "0", 10);
          floatData = pcmToFloat32(response.data);
          console.log(`[Playback] Block ${blockId} ${modelSlug} synthesis in ${(performance.now() - startTime).toFixed(0)}ms`);
        } else {
          // Browser-side synthesis via Kokoro.js Web Worker
          const result = await browserTTS.synthesize(block.text, { voice: voiceSelection.voiceSlug });
          floatData = result.audio;
          sampleRate = result.sampleRate;
          durationMs = Math.round((floatData.length / sampleRate) * 1000);
          console.log(`[Playback] Block ${blockId} browser synthesis in ${(performance.now() - startTime).toFixed(0)}ms`);
        }

        // Create AudioBuffer at native sample rate
        const audioBuffer = audioContextRef.current!.createBuffer(1, floatData.length, sampleRate);
        audioBuffer.getChannelData(0).set(floatData);

        const actualDurationMs = durationMs || Math.round(audioBuffer.duration * 1000);

        const audioBufferData: AudioBufferData = {
          buffer: audioBuffer,
          duration_ms: actualDurationMs
        };

        // Store in buffer map
        audioBuffersRef.current.set(blockId, audioBufferData);

        // Calculate and store duration correction
        const estimatedDuration = block.est_duration_ms || 0;
        const correction = actualDurationMs - estimatedDuration;
        durationCorrectionsRef.current.set(blockId, correction);

        // Recalculate total if we have initial estimate
        if (initialTotalEstimateRef.current > 0) {
          const totalCorrection = Array.from(durationCorrectionsRef.current.values()).reduce((sum, corr) => sum + corr, 0);
          const newTotal = initialTotalEstimateRef.current + totalCorrection;
          setActualTotalDuration(newTotal);
        }

        return audioBufferData;
      } catch (error) {
        console.error("[Playback] Error synthesizing block:", error);
        setIsPlaying(false);
        return null;
      } finally {
        // Always clear the synthesizing promise when done
        synthesizingRef.current.delete(blockId);
      }
    })();

    // Store the promise so others can await it
    synthesizingRef.current.set(blockId, synthesisPromise);

    return synthesisPromise;
  }, [api, browserTTS.synthesize, documentBlocks, documentId, voiceSelection]);

  const playAudioBuffer = useCallback(async (audioBufferData: AudioBufferData) => {
    if (!audioPlayerRef.current) return;

    // Store current block duration for progress calculation
    currentBlockDurationRef.current = audioBufferData.duration_ms;

    // Stop any currently playing audio first
    audioPlayerRef.current.stop();

    // Set up onEnded callback for auto-advance
    audioPlayerRef.current.setOnEnded(() => {
      // Add current block duration to cumulative progress
      blockStartTimeRef.current += currentBlockDurationRef.current;

      setCurrentBlock(prev => {
        if (documentBlocks && prev < documentBlocks.length - 1) {
          return prev + 1;
        } else {
          setIsPlaying(false);
          setAudioProgress(0);
          blockStartTimeRef.current = 0;
          return -1;
        }
      });
    });

    // Load audio (wait for it to be ready) then play
    await audioPlayerRef.current.load(audioBufferData.buffer);
    await audioPlayerRef.current.play();
  }, [documentBlocks]);

  // Handle pending voice change restart (runs after synthesizeBlock is recreated with new voice)
  useEffect(() => {
    if (!pendingVoiceChangeRef.current) return;
    pendingVoiceChangeRef.current = false;

    const blockId = documentBlocks[currentBlock]?.id;
    if (blockId === undefined) return;

    // Synthesize with new voice and play
    synthesizeBlock(blockId).then(audioData => {
      setIsSynthesizing(false);
      if (audioData && isPlayingRef.current) {
        playAudioBuffer(audioData);
      } else if (!audioData && isPlayingRef.current) {
        // Synthesis failed after voice change - auto-advance
        console.error(`[Playback] SYNTHESIS FAILED after voice change for block ${blockId}, auto-advancing`);
        setCurrentBlock(prev => {
          if (documentBlocks && prev < documentBlocks.length - 1) {
            return prev + 1;
          } else {
            setIsPlaying(false);
            return -1;
          }
        });
      }
    });
  }, [synthesizeBlock, currentBlock, documentBlocks, playAudioBuffer]);

  // Keep isPlayingRef in sync with state
  useEffect(() => {
    isPlayingRef.current = isPlaying;
  }, [isPlaying]);

  // Handle block changes and pre-synthesis
  useEffect(() => {
    if (!documentBlocks || currentBlock === -1 || !isPlaying) {
      setIsSynthesizing(false);
      return;
    }

    console.log(`[Playback] Block change: currentBlock=${currentBlock}, cache size=${audioBuffersRef.current.size}`);

    const PREFETCH_COUNT = 2;
    const EVICT_THRESHOLD = 5; // Remove buffers this many blocks behind

    // IMPORTANT: Play/synthesize current block FIRST before prefetching
    if (currentBlock < documentBlocks.length) {
      const currentBlockId = documentBlocks[currentBlock]?.id;
      if (!currentBlockId) return;

      const audioData = audioBuffersRef.current.get(currentBlockId);
      if (audioData) {
        console.log(`[Playback] Cache HIT for block ${currentBlockId}, playing immediately`);
        setIsSynthesizing(false);
        playAudioBuffer(audioData);
      } else {
        // Show loading state while synthesizing current block
        console.log(`[Playback] Cache MISS for block ${currentBlockId}, synthesizing FIRST...`);
        setIsSynthesizing(true);
        synthesizeBlock(currentBlockId).then(audioData => {
          setIsSynthesizing(false);
          if (audioData && isPlayingRef.current) {
            playAudioBuffer(audioData);
          } else if (!audioData && isPlayingRef.current) {
            // Synthesis failed (empty block, network error, etc.) - auto-advance
            console.error(`[Playback] SYNTHESIS FAILED for block ${currentBlockId} (idx ${currentBlock}), auto-advancing to next block`);
            setCurrentBlock(prev => {
              if (documentBlocks && prev < documentBlocks.length - 1) {
                return prev + 1;
              } else {
                setIsPlaying(false);
                return -1;
              }
            });
          }
        });
      }
    }

    // Pre-synthesize upcoming blocks AFTER current block is queued
    // (fire and forget - they cache themselves)
    for (let i = 1; i <= PREFETCH_COUNT; i++) {
      const targetIdx = currentBlock + i;
      if (targetIdx < documentBlocks.length) {
        const blockId = documentBlocks[targetIdx].id;
        if (!audioBuffersRef.current.has(blockId)) {
          console.log(`[Playback] Prefetching block ${blockId} (idx ${targetIdx})`);
          synthesizeBlock(blockId);
        }
      }
    }

    // Evict old buffers to limit memory on long documents
    if (currentBlock > EVICT_THRESHOLD) {
      for (let i = 0; i < currentBlock - EVICT_THRESHOLD; i++) {
        const oldBlockId = documentBlocks[i]?.id;
        if (oldBlockId && audioBuffersRef.current.has(oldBlockId)) {
          console.log(`[Playback] Evicting block ${oldBlockId} (idx ${i})`);
          audioBuffersRef.current.delete(oldBlockId);
        }
      }
    }
  }, [currentBlock, isPlaying, documentBlocks, playAudioBuffer, synthesizeBlock]);


  const handlePlay = async () => {
    if (isPlaying) return;

    if (audioContextRef.current?.state === 'suspended') {
      await audioContextRef.current.resume();
    }

    setIsPlaying(true);

    if (currentBlock === -1) {
      setCurrentBlock(0);
      setAudioProgress(0);
      blockStartTimeRef.current = 0;
    }
  };

  const handlePause = () => {
    setIsPlaying(false);
    audioPlayerRef.current?.pause();
  };

  // Keep refs updated for keyboard handler (avoids stale closures)
  handlePlayRef.current = handlePlay;
  handlePauseRef.current = handlePause;

  // Cancel synthesis - stop waiting for TTS, reset to ready state
  const handleCancelSynthesis = () => {
    setIsPlaying(false);
    setIsSynthesizing(false);
    audioPlayerRef.current?.stop();

    // Clear pending synthesis queue (let in-progress ones finish, they'll just cache)
    synthesizingRef.current.clear();
  };

  const handleSkipBack = () => {
    // Stop current audio
    audioPlayerRef.current?.stop();

    blockStartTimeRef.current = 0;
    setAudioProgress(0);

    if (currentBlock > 0) {
      setCurrentBlock(currentBlock - 1);
    } else if (currentBlock === 0 && isPlaying && documentBlocks.length > 0) {
      // Restart current block - directly play since effect won't re-trigger
      const blockId = documentBlocks[0].id;
      const audioData = audioBuffersRef.current.get(blockId);
      if (audioData) {
        playAudioBuffer(audioData);
      } else {
        synthesizeBlock(blockId).then(data => {
          if (data && isPlayingRef.current) {
            playAudioBuffer(data);
          } else if (!data) {
            console.error(`[Playback] SYNTHESIS FAILED for block ${blockId} on skip-back restart`);
          }
        });
      }
    }
  };

  const handleSkipForward = () => {
    if (documentBlocks && currentBlock < documentBlocks.length - 1) {
      // Stop current audio
      audioPlayerRef.current?.stop();

      // Calculate progress up to the new block
      const newBlock = currentBlock + 1;
      let progressMs = 0;
      for (let i = 0; i < newBlock; i++) {
        const blockData = audioBuffersRef.current.get(documentBlocks[i].id);
        progressMs += blockData?.duration_ms ?? documentBlocks[i].est_duration_ms ?? 0;
      }
      blockStartTimeRef.current = progressMs;
      setAudioProgress(progressMs);
      setCurrentBlock(newBlock);
    }
  };

  // Memoized to prevent StructuredDocumentView re-renders from audioProgress updates
  const handleBlockChange = useCallback((newBlock: number) => {
    if (newBlock === currentBlock) return;
    if (!documentBlocks || newBlock < 0 || newBlock >= documentBlocks.length) return;

    audioPlayerRef.current?.stop();

    // Calculate progress up to the new block
    let progressMs = 0;
    for (let i = 0; i < newBlock; i++) {
      const blockData = audioBuffersRef.current.get(documentBlocks[i].id);
      progressMs += blockData?.duration_ms ?? documentBlocks[i].est_duration_ms ?? 0;
    }
    blockStartTimeRef.current = progressMs;
    setAudioProgress(progressMs);
    setCurrentBlock(newBlock);

    // If already playing, the useEffect will auto-play the new block
    // If paused, just set position (user can press play)
  }, [currentBlock, documentBlocks]);

  // Handle click on structured document block (by audio_block_idx)
  // Memoized to prevent StructuredDocumentView re-renders from audioProgress updates
  const handleDocumentBlockClick = useCallback((audioBlockIdx: number) => {
    handleBlockChange(audioBlockIdx);
  }, [handleBlockChange]);

  const handleVolumeChange = (newVolume: number) => {
    setVolume(newVolume);
  };

  const handleSpeedChange = (newSpeed: number) => {
    setPlaybackSpeed(newSpeed);
  };

  if (isLoading) {
    return (
      <div className="flex grow items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex grow items-center justify-center text-destructive">
        {error}
      </div>
    );
  }

  return (
    <div className="flex grow pb-32">
      <StructuredDocumentView
        structuredContent={structuredContent}
        title={documentTitle}
        currentAudioBlockIdx={currentBlock}
        onBlockClick={handleDocumentBlockClick}
        fallbackContent={fallbackContent}
      />
      <SoundControl
        isPlaying={isPlaying}
        isSynthesizing={isSynthesizing}
        onPlay={handlePlay}
        onPause={handlePause}
        onCancelSynthesis={handleCancelSynthesis}
        onSkipBack={handleSkipBack}
        onSkipForward={handleSkipForward}
        progressBarValues={{
          estimated_ms: actualTotalDuration > 0 ? actualTotalDuration : estimated_ms,
          numberOfBlocks,
          currentBlock: currentBlock >= 0 ? currentBlock : 0,
          setCurrentBlock: handleBlockChange,
          audioProgress,
        }}
        volume={volume}
        onVolumeChange={handleVolumeChange}
        playbackSpeed={playbackSpeed}
        onSpeedChange={handleSpeedChange}
        voiceSelection={voiceSelection}
        onVoiceChange={setVoiceSelection}
      />
    </div>
  );
};

export default PlaybackPage;
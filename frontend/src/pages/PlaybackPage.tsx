import { SoundControl } from '@/components/soundControl';
import { StructuredDocumentView } from '@/components/structuredDocument';
import { useParams, useLocation } from "react-router";
import { useRef, useState, useEffect, useCallback } from "react";
import { useApi } from '@/api';
import { Loader2 } from "lucide-react";
import { AudioPlayer } from '@/lib/audio';
import { useBrowserTTS } from '@/lib/browserTTS';
import { type VoiceSelection, getVoiceSelection } from '@/lib/voiceSelection';

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

const PlaybackPage = () => {
  const { documentId } = useParams<{ documentId: string }>();
  const { state } = useLocation();
  const initialTitle: string | undefined = state?.documentTitle;

  const { api, isAuthReady } = useApi();
  const browserTTS = useBrowserTTS();

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
  const [playbackSpeed, setPlaybackSpeed] = useState<number>(1.0);
  const [isSynthesizing, setIsSynthesizing] = useState<boolean>(false);
  const [voiceSelection, setVoiceSelection] = useState<VoiceSelection>(getVoiceSelection);

  // Audio setup variables
  const audioContextRef = useRef<AudioContext | null>(null);
  const gainNodeRef = useRef<GainNode | null>(null);
  const audioPlayerRef = useRef<AudioPlayer | null>(null);
  const [currentBlock, setCurrentBlock] = useState<number>(-1);
	const audioBuffersRef = useRef<Map<number, AudioBufferData>>(new Map());
	const synthesizingRef = useRef<Set<number>>(new Set()); // Track in-progress synthesis
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
    // Use 44100Hz because SoundTouchJS's time-stretch algorithm is hardcoded for 44100Hz
    // Web Audio API will automatically resample our 24000Hz audio
    if (!audioContextRef.current || audioContextRef.current.state === 'closed') {
      audioContextRef.current = new AudioContext({ sampleRate: 44100 });
      gainNodeRef.current = audioContextRef.current.createGain();
      gainNodeRef.current.connect(audioContextRef.current.destination);
      gainNodeRef.current.gain.value = volume / 100;
    }

    // Create AudioPlayer if needed (with pitch-preserving speed control)
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

    // Check if synthesis already in progress
    if (synthesizingRef.current.has(blockId)) {
      console.log(`[Playback] Block ${blockId} already synthesizing, skipping`);
      return null;
    }

    try {
      // Find the block to get its text
      const block = documentBlocks.find(b => b.id === blockId);
      if (!block) {
        console.error("[Playback] Block not found:", blockId);
        return null;
      }

      if (!audioContextRef.current) {
        return null;
      }

      // Mark as synthesizing
      synthesizingRef.current.add(blockId);
      console.log(`[Playback] Starting synthesis for block ${blockId} (idx ${block.idx}, ${block.text.length} chars)`);
      const startTime = performance.now();

      // Synthesize using browser TTS (Kokoro.js in Web Worker)
      const voice = voiceSelection.model === "kokoro" ? voiceSelection.voiceSlug : "af_heart";
      const { audio: floatData, sampleRate } = await browserTTS.synthesize(block.text, { voice });
      console.log(`[Playback] Block ${blockId} synthesized in ${(performance.now() - startTime).toFixed(0)}ms`);

      // Resample from 24000Hz to 44100Hz for SoundTouchJS compatibility
      const inputFrames = floatData.length;
      const targetSampleRate = 44100;
      const resampleRatio = targetSampleRate / sampleRate;
      const outputFrames = Math.ceil(inputFrames * resampleRatio);

      const audioBuffer = audioContextRef.current.createBuffer(1, outputFrames, targetSampleRate);
      const outputData = audioBuffer.getChannelData(0);

      // Linear interpolation resampling
      for (let outFrame = 0; outFrame < outputFrames; outFrame++) {
        const inPos = outFrame / resampleRatio;
        const inFrame = Math.floor(inPos);
        const frac = inPos - inFrame;

        const sample1 = floatData[inFrame] ?? 0;
        const sample2 = floatData[Math.min(inFrame + 1, inputFrames - 1)] ?? 0;
        outputData[outFrame] = sample1 + frac * (sample2 - sample1);
      }

      const actualDurationMs = Math.round(audioBuffer.duration * 1000);

      const audioBufferData: AudioBufferData = {
        buffer: audioBuffer,
        duration_ms: actualDurationMs
      };

      // Store in buffer map and clear synthesizing flag
      audioBuffersRef.current.set(blockId, audioBufferData);
      synthesizingRef.current.delete(blockId);

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
      synthesizingRef.current.delete(blockId);
      setIsPlaying(false);
      return null;
    }
  }, [browserTTS.synthesize, documentBlocks, voiceSelection]);

  const playAudioBuffer = useCallback((audioBufferData: AudioBufferData) => {
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

    // Load and play the buffer
    audioPlayerRef.current.load(audioBufferData.buffer);
    audioPlayerRef.current.play();
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

  const handleBlockChange = (newBlock: number) => {
    if (newBlock === currentBlock) return;
    if (!documentBlocks || newBlock < 0 || newBlock >= documentBlocks.length) return;

    // Stop current audio
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
  };

  // Handle click on structured document block (by audio_block_idx)
  const handleDocumentBlockClick = (audioBlockIdx: number) => {
    // audio_block_idx maps directly to documentBlocks index
    handleBlockChange(audioBlockIdx);
  };

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
import { SoundControl } from '@/components/soundControl';
import { StructuredDocumentView } from '@/components/structuredDocument';
import { useParams, useLocation, Link } from "react-router";
import { useRef, useState, useEffect, useLayoutEffect, useCallback, useMemo } from "react";
import { useApi } from '@/api';
import { Loader2, FileQuestion } from "lucide-react";
import { AxiosError } from "axios";
import { AudioPlayer } from '@/lib/audio';
import { useBrowserTTS } from '@/lib/browserTTS';
import { type VoiceSelection, getVoiceSelection, getBackendModelSlug, isServerSideModel } from '@/lib/voiceSelection';
import { useSettings } from '@/hooks/useSettings';
import { useTTSWebSocket } from '@/hooks/useTTSWebSocket';

// Playback position persistence
const POSITION_KEY_PREFIX = "yapit_playback_position_";

// Parallel prefetch configuration
const BATCH_SIZE = 8;           // Blocks per request
const REFILL_THRESHOLD = 8;     // When ready_ahead < this, request more
const MIN_BUFFER_TO_START = 4;  // Minimum cached blocks before starting playback

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

interface DocumentMetadata {
  content_type?: string;
  page_count?: number;
  title?: string;
  url?: string;
  file_name?: string;
  file_size?: number;
}

interface DocumentResponse {
  id: string;
  title: string | null;
  original_text: string;
  filtered_text: string | null;
  structured_content: string | null;
  metadata_dict: DocumentMetadata | null;
  last_block_idx: number | null;
}

interface AudioBufferData {
  buffer: AudioBuffer;
  duration_ms: number;
}


const PlaybackPage = () => {
  const { documentId } = useParams<{ documentId: string }>();
  const { state } = useLocation();
  const initialTitle: string | undefined = state?.documentTitle;

  const { api, isAuthReady, isAnonymous } = useApi();
  const browserTTS = useBrowserTTS();
  const { settings } = useSettings();
  const ttsWS = useTTSWebSocket();

  // Document data fetched from API
  const [document, setDocument] = useState<DocumentResponse | null>(null);
  const [documentBlocks, setDocumentBlocks] = useState<Block[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Derived state
  const documentTitle = document?.title ?? initialTitle;
  const structuredContent = document?.structured_content ?? null;
  const fallbackContent = document?.filtered_text ?? document?.original_text ?? "";
  const sourceUrl = document?.metadata_dict?.url ?? null;
  const markdownContent = document?.filtered_text ?? document?.original_text ?? null;
  const numberOfBlocks = documentBlocks.length;
  const estimated_ms = documentBlocks.reduce((sum, b) => sum + (b.est_duration_ms || 0), 0);

  // Sound control variables
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const isPlayingRef = useRef<boolean>(false); // Ref to track current state for async callbacks
  const [isBuffering, setIsBuffering] = useState<boolean>(false); // Waiting for initial buffer to fill
  const isBufferingRef = useRef<boolean>(false); // Ref for async callbacks
  const [volume, setVolume] = useState<number>(50);
  const [playbackSpeed, setPlaybackSpeed] = useState<number>(settings.defaultSpeed);
  const [isSynthesizing, setIsSynthesizing] = useState<boolean>(false);
  const [voiceSelection, setVoiceSelection] = useState<VoiceSelection>(getVoiceSelection);

  // Audio setup variables
  const audioContextRef = useRef<AudioContext | null>(null);
  const gainNodeRef = useRef<GainNode | null>(null);
  const audioPlayerRef = useRef<AudioPlayer | null>(null);
  const [currentBlock, setCurrentBlock] = useState<number>(-1);
  const currentBlockRef = useRef<number>(-1);
  currentBlockRef.current = currentBlock; // Sync ref with state for use in callbacks
	const audioBuffersRef = useRef<Map<number, AudioBufferData>>(new Map());
	const synthesizingRef = useRef<Map<number, Promise<AudioBufferData | null>>>(new Map()); // Track in-progress synthesis promises
	// Track blocks we've ever received audio for this session (for visual state only)
	// Unlike audioBuffersRef which evicts old blocks, this persists to show accurate "cached" state
	const cachedBlocksRef = useRef<Set<number>>(new Set());
	const [audioProgress, setAudioProgress] = useState<number>(0);
	const blockStartTimeRef = useRef<number>(0);
	const [actualTotalDuration, setActualTotalDuration] = useState<number>(0);
	const durationCorrectionsRef = useRef<Map<number, number>>(new Map());
	const initialTotalEstimateRef = useRef<number>(0);
  const currentBlockDurationRef = useRef<number>(0);

  // Track previous block for DOM-based highlighting (avoids React re-renders)
  const prevBlockIdxRef = useRef<number>(-1);

  // Hover/drag highlighting - refs instead of state to avoid re-renders
  // These drive purely imperative DOM updates (class manipulation + scroll)
  const hoveredBlockRef = useRef<number | null>(null);
  const isDraggingProgressBarRef = useRef(false);
  const lastHoverScrollTimeRef = useRef<number>(0);

  // Handler for progress bar hover/drag - direct DOM manipulation, no state
  const handleBlockHover = useCallback((idx: number | null, isDragging: boolean) => {
    const prevHovered = hoveredBlockRef.current;
    hoveredBlockRef.current = idx;
    isDraggingProgressBarRef.current = isDragging;

    const HOVER_BLOCK_CLASS = "audio-block-hovered";

    // Remove hover class from previous block
    if (prevHovered !== null && prevHovered !== idx) {
      window.document.querySelectorAll(`[data-audio-block-idx="${prevHovered}"]`)
        .forEach(el => el.classList.remove(HOVER_BLOCK_CLASS));
    }

    // Add hover class to currently hovered block (if not same as active playing block)
    if (idx !== null && idx !== currentBlockRef.current) {
      window.document.querySelectorAll(`[data-audio-block-idx="${idx}"]`)
        .forEach(el => el.classList.add(HOVER_BLOCK_CLASS));
    }

    // Clear hover class if hovering over the active block or leaving
    if (idx === null || idx === currentBlockRef.current) {
      if (prevHovered !== null) {
        window.document.querySelectorAll(`[data-audio-block-idx="${prevHovered}"]`)
          .forEach(el => el.classList.remove(HOVER_BLOCK_CLASS));
      }
    }

    // Scroll to hovered block during drag (throttled, only when off-screen)
    if (isDragging && idx !== null && idx !== currentBlockRef.current) {
      const SCROLL_THROTTLE_MS = 500;
      const now = Date.now();
      if (now - lastHoverScrollTimeRef.current >= SCROLL_THROTTLE_MS) {
        const element = window.document.querySelector(`[data-audio-block-idx="${idx}"]`);
        if (element) {
          const rect = element.getBoundingClientRect();
          const margin = 50;
          const isVisible = rect.top >= margin && rect.bottom <= window.innerHeight - margin;
          if (!isVisible) {
            element.scrollIntoView({ behavior: "auto", block: "center" });
            lastHoverScrollTimeRef.current = now;
          }
        }
      }
    }
  }, []);

  // Parallel prefetch tracking
  const prefetchedUpToRef = useRef<number>(-1); // Highest block index we've triggered prefetch for
  const playingBlockRef = useRef<number>(-1); // Block currently being played (prevents duplicate play calls)

  // Block states for progress bar visualization
  // 'pending' = not started, 'synthesizing' = in progress, 'cached' = ready
  type BlockState = 'pending' | 'synthesizing' | 'cached';
  const [blockStates, setBlockStates] = useState<BlockState[]>([]);
  const [blockStateVersion, setBlockStateVersion] = useState(0); // Trigger re-derive
  const blockStateVersionTimeoutRef = useRef<number | null>(null); // Debounce version updates

  // Debounced version increment - batches rapid completions into single update
  const bumpBlockStateVersion = useCallback(() => {
    if (blockStateVersionTimeoutRef.current) {
      clearTimeout(blockStateVersionTimeoutRef.current);
    }
    blockStateVersionTimeoutRef.current = window.setTimeout(() => {
      setBlockStateVersion(v => v + 1);
      blockStateVersionTimeoutRef.current = null;
    }, 50); // 50ms debounce - fast enough to feel responsive, slow enough to batch
  }, []);

  // DOM-based active block highlighting - directly manipulate CSS classes
  // This runs synchronously before browser paint to avoid flicker
  // Note: Use window.document because there's a local `document` state variable
  useLayoutEffect(() => {
    const ACTIVE_BLOCK_CLASS = "audio-block-active";

    // Remove active class from previous block
    if (prevBlockIdxRef.current >= 0) {
      const prevElements = window.document.querySelectorAll(
        `[data-audio-block-idx="${prevBlockIdxRef.current}"]`
      );
      prevElements.forEach((el) => el.classList.remove(ACTIVE_BLOCK_CLASS));
    }

    // Add active class to current block
    if (currentBlock >= 0) {
      const currentElements = window.document.querySelectorAll(
        `[data-audio-block-idx="${currentBlock}"]`
      );
      currentElements.forEach((el) => el.classList.add(ACTIVE_BLOCK_CLASS));
    }

    prevBlockIdxRef.current = currentBlock;
  }, [currentBlock]);

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
        if (err instanceof AxiosError && (err.response?.status === 404 || err.response?.status === 422)) {
          // 404 = doc doesn't exist, 422 = invalid UUID format (same user experience)
          setError("not_found");
        } else {
          setError(err instanceof Error ? err.message : "Failed to fetch document");
        }
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
      prefetchedUpToRef.current = -1; // Reset prefetch tracking
      ttsWS.reset(); // Reset WS state
    };
  }, [documentId, ttsWS.reset]);

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

  // Restore playback position when document loads
  // For authenticated users: prefer server's last_block_idx for cross-device sync
  // For anonymous users: use localStorage
  useEffect(() => {
    if (!documentId || documentBlocks.length === 0 || !document) return;

    // Prefer server position for authenticated users (cross-device sync)
    const serverBlock = document.last_block_idx;
    const localSaved = getPlaybackPosition(documentId);

    // Use server position if authenticated and server has a saved position
    // Otherwise fall back to localStorage
    let restoreBlock: number | null = null;
    let restoreProgressMs = 0;

    if (!isAnonymous && serverBlock !== null && serverBlock >= 0 && serverBlock < documentBlocks.length) {
      restoreBlock = serverBlock;
      // Estimate progress to this block for display
      for (let i = 0; i < serverBlock; i++) {
        restoreProgressMs += documentBlocks[i].est_duration_ms || 0;
      }
    } else if (localSaved && localSaved.block >= 0 && localSaved.block < documentBlocks.length) {
      restoreBlock = localSaved.block;
      restoreProgressMs = localSaved.progressMs;
    }

    if (restoreBlock !== null) {
      setCurrentBlock(restoreBlock);
      setAudioProgress(restoreProgressMs);
      blockStartTimeRef.current = restoreProgressMs;

      // Scroll to restored block after React renders the blocks
      if (settings.scrollOnRestore) {
        setTimeout(() => {
          const blockElement = window.document.querySelector(
            `[data-audio-block-idx="${restoreBlock}"]`
          );
          if (blockElement) {
            blockElement.scrollIntoView({ behavior: "smooth", block: "center" });
          }
        }, 100);
      }
    }
  }, [documentId, documentBlocks, document, isAnonymous, settings.scrollOnRestore]);

  // Ref to track documentId for position saving (avoids saving old position to new doc on navigation)
  const documentIdRef = useRef(documentId);
  documentIdRef.current = documentId;

  // Track isAnonymous via ref to avoid re-triggering on auth changes
  const isAnonymousRef = useRef(isAnonymous);
  isAnonymousRef.current = isAnonymous;

  // Save playback position when currentBlock changes
  // Uses ref for documentId so navigating to a new doc doesn't save old position to new doc's key
  useEffect(() => {
    if (!documentIdRef.current || currentBlock < 0) return;

    // Always save to localStorage (instant, serves as fallback if server sync fails)
    setPlaybackPosition(documentIdRef.current, {
      block: currentBlock,
      progressMs: blockStartTimeRef.current,
    });

    // Sync to server for authenticated users (cross-device sync)
    if (!isAnonymousRef.current) {
      api.patch(`/v1/documents/${documentIdRef.current}/position`, {
        block_idx: currentBlock,
      }).catch(() => {
        // Silently ignore sync failures - localStorage is the fallback
      });
    }
  }, [currentBlock, api]); // Only depend on currentBlock - documentId and isAnonymous come from refs

  // Helper to scroll to a specific block
  const scrollToBlock = useCallback((blockIdx: number, behavior: ScrollBehavior = "smooth") => {
    if (blockIdx < 0 || !settings.liveScrollTracking) return;
    const blockElement = window.document.querySelector(
      `[data-audio-block-idx="${blockIdx}"]`
    );
    if (blockElement) {
      blockElement.scrollIntoView({ behavior, block: "center" });
    }
  }, [settings.liveScrollTracking]);

  // Live scroll tracking - keep current block visible during playback
  useEffect(() => {
    // Scroll when block changes during playback
    if (currentBlock < 0 || !isPlayingRef.current || !settings.liveScrollTracking) return;
    scrollToBlock(currentBlock);
  }, [currentBlock, settings.liveScrollTracking, scrollToBlock]);

  // Scroll to current block immediately when playback starts
  useEffect(() => {
    if (isPlaying && settings.liveScrollTracking && currentBlock >= 0) {
      scrollToBlock(currentBlock);
    }
  }, [isPlaying, settings.liveScrollTracking, currentBlock, scrollToBlock]);

  // Derive block states from refs (browser mode) or WS (server mode)
  const isServerMode = isServerSideModel(voiceSelection.model);

  useEffect(() => {
    if (!documentBlocks || documentBlocks.length === 0) {
      setBlockStates([]);
      return;
    }

    const states: BlockState[] = documentBlocks.map((block, idx) => {
      const wsStatus = isServerMode ? ttsWS.blockStates.get(idx) : undefined;

      // Use cachedBlocksRef for visual state, but only if we still have access to audio.
      // If backend evicted (wsStatus undefined), we need buffer locally to show as cached.
      if (cachedBlocksRef.current.has(block.id)) {
        if (audioBuffersRef.current.has(block.id) || wsStatus === 'cached') {
          return 'cached';
        }
        // Backend evicted and no local buffer - fall through to pending
      }

      if (isServerMode) {
        // Server mode: use WS block states
        if (wsStatus === 'cached') return 'cached';
        if (wsStatus === 'queued' || wsStatus === 'processing') return 'synthesizing';
        return 'pending';
      } else {
        // Browser mode: use local synthesizing ref
        if (synthesizingRef.current.has(block.id)) return 'synthesizing';
        return 'pending';
      }
    });
    setBlockStates(states);
  }, [documentBlocks, blockStateVersion, isServerMode, ttsWS.blockStates]);

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

  // MediaSession handlers for hardware media keys (headphones, keyboards)
  useEffect(() => {
    if (!("mediaSession" in navigator)) return;

    navigator.mediaSession.setActionHandler("play", () => {
      handlePlayRef.current();
    });
    navigator.mediaSession.setActionHandler("pause", () => {
      handlePauseRef.current();
    });

    return () => {
      navigator.mediaSession.setActionHandler("play", null);
      navigator.mediaSession.setActionHandler("pause", null);
    };
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

  // Helper to fetch audio from HTTP and create AudioBuffer
  const fetchAudioFromUrl = useCallback(async (audioUrl: string, blockId: number): Promise<AudioBufferData | null> => {
    if (!audioContextRef.current) return null;

    try {
      const response = await api.get(audioUrl, { responseType: "arraybuffer" });
      const durationMs = parseInt(response.headers["x-duration-ms"] || "0", 10);

      // decodeAudioData handles WAV, MP3, and other browser-supported formats
      const audioBuffer = await audioContextRef.current.decodeAudioData(response.data.slice(0));

      const actualDurationMs = durationMs || Math.round(audioBuffer.duration * 1000);
      const audioBufferData: AudioBufferData = {
        buffer: audioBuffer,
        duration_ms: actualDurationMs,
      };

      // Cache locally
      audioBuffersRef.current.set(blockId, audioBufferData);
      cachedBlocksRef.current.add(blockId);

      // Update duration correction
      const block = documentBlocks.find(b => b.id === blockId);
      if (block) {
        const correction = actualDurationMs - (block.est_duration_ms || 0);
        durationCorrectionsRef.current.set(blockId, correction);
        if (initialTotalEstimateRef.current > 0) {
          const totalCorrection = Array.from(durationCorrectionsRef.current.values()).reduce((sum, c) => sum + c, 0);
          setActualTotalDuration(initialTotalEstimateRef.current + totalCorrection);
        }
      }

      return audioBufferData;
    } catch (error) {
      console.error("[Playback] Error fetching audio:", error);
      return null;
    }
  }, [api, documentBlocks]);

  // When voice changes: clear cache and mark for restart if playing/buffering
  const voiceSelectionRef = useRef(voiceSelection);
  const pendingVoiceChangeRef = useRef(false);
  const wasBufferingOnVoiceChangeRef = useRef(false); // Track if we were buffering (vs playing)
  useEffect(() => {
    const voiceChanged = voiceSelectionRef.current.model !== voiceSelection.model ||
                         voiceSelectionRef.current.voiceSlug !== voiceSelection.voiceSlug;
    voiceSelectionRef.current = voiceSelection;

    if (!voiceChanged) return;

    // Clear all cached audio (synthesized with old voice)
    audioBuffersRef.current.clear();
    cachedBlocksRef.current.clear();
    synthesizingRef.current.clear();
    durationCorrectionsRef.current.clear();
    prefetchedUpToRef.current = -1; // Reset prefetch tracking
    ttsWS.reset(); // Reset WS state (server mode)

    // If we were playing or buffering, mark that we need to restart
    const wasActive = isPlayingRef.current || isBufferingRef.current;
    if (wasActive && currentBlock >= 0) {
      wasBufferingOnVoiceChangeRef.current = isBufferingRef.current && !isPlayingRef.current;
      audioPlayerRef.current?.stop();
      setIsBuffering(false); // Cancel any in-progress buffering
      setIsSynthesizing(true);
      pendingVoiceChangeRef.current = true;
    }
  }, [voiceSelection, currentBlock, ttsWS.reset]);


  // Synthesize a single block for browser mode (local synthesis)
  const synthesizeBlockBrowser = useCallback(async (block: Block): Promise<AudioBufferData | null> => {
    if (!audioContextRef.current) return null;

    try {
      console.log(`[Playback] Browser synthesis for block ${block.id} (idx ${block.idx})`);
      const startTime = performance.now();

      const result = await browserTTS.synthesize(block.text, { voice: voiceSelection.voiceSlug });
      const { audio: floatData, sampleRate } = result;
      const durationMs = Math.round((floatData.length / sampleRate) * 1000);

      console.log(`[Playback] Block ${block.id} browser synthesis in ${(performance.now() - startTime).toFixed(0)}ms`);

      const audioBuffer = audioContextRef.current.createBuffer(1, floatData.length, sampleRate);
      audioBuffer.getChannelData(0).set(floatData);

      const audioBufferData: AudioBufferData = {
        buffer: audioBuffer,
        duration_ms: durationMs,
      };

      audioBuffersRef.current.set(block.id, audioBufferData);
      cachedBlocksRef.current.add(block.id);

      // Duration correction
      const correction = durationMs - (block.est_duration_ms || 0);
      durationCorrectionsRef.current.set(block.id, correction);
      if (initialTotalEstimateRef.current > 0) {
        const totalCorrection = Array.from(durationCorrectionsRef.current.values()).reduce((sum, c) => sum + c, 0);
        setActualTotalDuration(initialTotalEstimateRef.current + totalCorrection);
      }

      return audioBufferData;
    } catch (error) {
      console.error("[Playback] Browser synthesis error:", error);
      return null;
    }
  }, [browserTTS.synthesize, voiceSelection.voiceSlug]);

  // Get or wait for audio for a block (works for both browser and server mode)
  const synthesizeBlock = useCallback(async (blockId: number): Promise<AudioBufferData | null> => {
    // Check local cache first
    const cached = audioBuffersRef.current.get(blockId);
    if (cached) {
      console.log(`[Playback] Block ${blockId} cached locally, returning`);
      return cached;
    }

    // Check if already in progress
    const existingPromise = synthesizingRef.current.get(blockId);
    if (existingPromise) {
      console.log(`[Playback] Block ${blockId} already synthesizing, awaiting`);
      return existingPromise;
    }

    const block = documentBlocks.find(b => b.id === blockId);
    if (!block || !audioContextRef.current) return null;

    if (!isServerSideModel(voiceSelection.model)) {
      // Browser mode: synthesize locally
      const synthesisPromise = synthesizeBlockBrowser(block);
      synthesizingRef.current.set(blockId, synthesisPromise);
      setBlockStateVersion(v => v + 1);
      synthesisPromise.finally(() => {
        synthesizingRef.current.delete(blockId);
        setBlockStateVersion(v => v + 1);
      });
      return synthesisPromise;
    }

    // Server mode: check WS for audio URL, or wait for it
    const synthesisPromise = (async (): Promise<AudioBufferData | null> => {
      try {
        const MAX_WAIT_MS = 60000;
        const POLL_INTERVAL_MS = 100;
        const startTime = Date.now();

        // Wait for WS connection first (with timeout)
        while (!ttsWS.checkConnected() && Date.now() - startTime < MAX_WAIT_MS) {
          await new Promise(resolve => setTimeout(resolve, POLL_INTERVAL_MS));
        }
        if (!ttsWS.checkConnected()) {
          console.error(`[Playback] WS connection timeout for block ${block.idx}`);
          return null;
        }

        // Check if WS already has audio URL
        let audioUrl = ttsWS.getAudioUrl(block.idx);
        if (audioUrl) {
          console.log(`[Playback] Block ${block.idx} has audio URL from WS, fetching`);
          return await fetchAudioFromUrl(audioUrl, blockId);
        }

        // Request synthesis via WS if not already queued/processing
        const wsStatus = ttsWS.getBlockStatus(block.idx);
        if (!wsStatus || wsStatus === 'pending' || wsStatus === 'error') {
          console.log(`[Playback] Requesting block ${block.idx} via WS`);
          ttsWS.synthesize({
            documentId: documentId!,
            blockIndices: [block.idx],
            cursor: currentBlockRef.current,
            model: getBackendModelSlug(voiceSelection.model),
            voice: voiceSelection.voiceSlug,
          });
        }

        // Poll for audio URL
        while (Date.now() - startTime < MAX_WAIT_MS) {
          audioUrl = ttsWS.getAudioUrl(block.idx);
          if (audioUrl) {
            console.log(`[Playback] Block ${block.idx} ready after ${Date.now() - startTime}ms, fetching`);
            return await fetchAudioFromUrl(audioUrl, blockId);
          }

          if (ttsWS.getBlockStatus(block.idx) === 'error') {
            console.error(`[Playback] Block ${block.idx} synthesis error from server`);
            return null;
          }

          await new Promise(resolve => setTimeout(resolve, POLL_INTERVAL_MS));
        }

        console.error(`[Playback] Timeout waiting for block ${block.idx}`);
        return null;
      } catch (error) {
        console.error("[Playback] Server synthesis error:", error);
        return null;
      }
    })();

    synthesizingRef.current.set(blockId, synthesisPromise);
    setBlockStateVersion(v => v + 1);
    synthesisPromise.finally(() => {
      synthesizingRef.current.delete(blockId);
      setBlockStateVersion(v => v + 1);
    });

    return synthesisPromise;
  }, [documentBlocks, documentId, voiceSelection, synthesizeBlockBrowser, fetchAudioFromUrl, ttsWS]);

  // Trigger prefetch for a range of blocks (fire and forget)
  const triggerPrefetchBatch = useCallback((fromIdx: number, count: number) => {
    if (!documentBlocks || documentBlocks.length === 0 || !documentId) return;

    const maxIdx = documentBlocks.length - 1;
    const toIdx = Math.min(fromIdx + count - 1, maxIdx);

    console.log(`[Prefetch] Triggering batch: blocks ${fromIdx} to ${toIdx} (${toIdx - fromIdx + 1} blocks)`);

    if (isServerSideModel(voiceSelection.model)) {
      if (!ttsWS.checkConnected()) {
        console.log(`[Prefetch] Skipping batch - WS not connected`);
        return;
      }

      const indicesToRequest: number[] = [];
      for (let idx = fromIdx; idx <= toIdx; idx++) {
        const block = documentBlocks[idx];
        if (!block) continue;
        if (audioBuffersRef.current.has(block.id)) continue;
        const wsStatus = ttsWS.getBlockStatus(idx);
        if (wsStatus === 'cached' || wsStatus === 'queued' || wsStatus === 'processing' || wsStatus === 'skipped') continue;
        indicesToRequest.push(idx);
      }

      if (indicesToRequest.length > 0) {
        ttsWS.synthesize({
          documentId,
          blockIndices: indicesToRequest,
          cursor: currentBlockRef.current,
          model: getBackendModelSlug(voiceSelection.model),
          voice: voiceSelection.voiceSlug,
        });
      }
    } else {
      // Browser mode: fire individual synthesis requests
      for (let idx = fromIdx; idx <= toIdx; idx++) {
        const block = documentBlocks[idx];
        if (!block) continue;
        if (audioBuffersRef.current.has(block.id)) continue;
        if (synthesizingRef.current.has(block.id)) continue;
        synthesizeBlock(block.id);
      }
    }

    // Track highest prefetched index
    if (toIdx > prefetchedUpToRef.current) {
      prefetchedUpToRef.current = toIdx;
    }
  }, [documentBlocks, documentId, voiceSelection, synthesizeBlock, ttsWS]);

  // Check buffer level and trigger refill if needed
  const checkAndRefillBuffer = useCallback(() => {
    if (!documentBlocks || documentBlocks.length === 0) return;

    const isServer = isServerSideModel(voiceSelection.model);

    // Count "ready" blocks ahead = cached + queued + processing
    // This prevents over-requesting when blocks are in-flight
    let readyAhead = 0;
    for (let idx = currentBlockRef.current + 1; idx < documentBlocks.length; idx++) {
      const block = documentBlocks[idx];
      // Check local cache first
      if (audioBuffersRef.current.has(block.id)) {
        readyAhead++;
        continue;
      }
      // For server mode, also count queued/processing from WS state
      if (isServer) {
        const wsStatus = ttsWS.getBlockStatus(idx);
        if (wsStatus === 'queued' || wsStatus === 'processing' || wsStatus === 'cached' || wsStatus === 'skipped') {
          readyAhead++;
          continue;
        }
      }
      // For browser mode, count synthesizing
      if (!isServer && synthesizingRef.current.has(block.id)) {
        readyAhead++;
        continue;
      }
      // Found a gap - stop counting contiguous ready blocks
      break;
    }

    // Only refill if we don't have enough ready blocks ahead
    if (readyAhead < REFILL_THRESHOLD) {
      // Find the first block that's not ready
      let firstUnreadyIdx = currentBlockRef.current + 1;
      for (let idx = currentBlockRef.current + 1; idx < documentBlocks.length; idx++) {
        const block = documentBlocks[idx];
        const isCached = audioBuffersRef.current.has(block.id);
        const isQueued = isServer && ['queued', 'processing', 'cached', 'skipped'].includes(ttsWS.getBlockStatus(idx) || '');
        const isSynthesizing = !isServer && synthesizingRef.current.has(block.id);
        if (!isCached && !isQueued && !isSynthesizing) {
          firstUnreadyIdx = idx;
          break;
        }
      }

      if (firstUnreadyIdx < documentBlocks.length) {
        console.log(`[Prefetch] Buffer low: ${readyAhead} ready ahead, requesting from block ${firstUnreadyIdx}`);
        triggerPrefetchBatch(firstUnreadyIdx, BATCH_SIZE);
      }
    }
  }, [documentBlocks, triggerPrefetchBatch, voiceSelection.model, ttsWS]);

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

    const wasBuffering = wasBufferingOnVoiceChangeRef.current;
    wasBufferingOnVoiceChangeRef.current = false;

    const blockId = documentBlocks[currentBlock]?.id;
    if (blockId === undefined) return;

    // If we were buffering, re-enter buffering state with new voice
    if (wasBuffering) {
      console.log(`[Playback] Voice changed during buffering, restarting buffer with new voice`);
      setIsSynthesizing(false);
      setIsBuffering(true);
      // Trigger prefetch for server mode
      if (isServerSideModel(voiceSelection.model) && ttsWS.checkConnected()) {
        triggerPrefetchBatch(currentBlock, BATCH_SIZE);
      }
      return;
    }

    // We were playing: synthesize current block with new voice and play
    synthesizeBlock(blockId).then(audioData => {
      // Check if this block is still the one we want (user may have clicked elsewhere)
      const stillCurrentBlock = documentBlocks[currentBlockRef.current]?.id === blockId;
      if (!stillCurrentBlock) {
        console.log(`[Playback] Voice change block ${blockId} finished but user moved, skipping`);
        return;
      }
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
  }, [synthesizeBlock, currentBlock, documentBlocks, playAudioBuffer, voiceSelection.model, ttsWS, triggerPrefetchBatch]);

  // Keep isPlayingRef in sync with state
  useEffect(() => {
    isPlayingRef.current = isPlaying;
  }, [isPlaying]);

  // Keep isBufferingRef in sync with state
  useEffect(() => {
    isBufferingRef.current = isBuffering;
  }, [isBuffering]);

  // Watch for buffer to fill during buffering state
  // When enough blocks are cached, transition to playing
  useEffect(() => {
    if (!isBuffering || !documentBlocks.length) return;

    const startBlock = currentBlockRef.current >= 0 ? currentBlockRef.current : 0;

    // Count resolved blocks ahead (cached or skipped)
    let cachedAhead = 0;
    for (let idx = startBlock; idx < documentBlocks.length; idx++) {
      const block = documentBlocks[idx];
      const isSkipped = ttsWS.blockStates.get(idx) === "skipped";
      if (audioBuffersRef.current.has(block.id) || isSkipped) {
        cachedAhead++;
      } else {
        break;
      }
    }

    // For short documents, don't require more blocks than exist
    const remainingBlocks = documentBlocks.length - startBlock;
    const requiredBuffer = Math.min(MIN_BUFFER_TO_START, remainingBlocks);

    console.log(`[Buffering] Progress: ${cachedAhead}/${requiredBuffer} blocks cached`);

    if (cachedAhead >= requiredBuffer) {
      console.log(`[Buffering] Buffer ready, starting playback`);
      setIsBuffering(false);
      setIsPlaying(true);
    }
  }, [isBuffering, documentBlocks, blockStateVersion, ttsWS.audioUrls, ttsWS.blockStates]);

  // Proactively fetch audio when WS reports blocks as cached (server mode only)
  // This ensures audio is ready before we try to play it
  useEffect(() => {
    if (!isServerMode || !documentBlocks.length) return;

    for (const [blockIdx, audioUrl] of ttsWS.audioUrls) {
      const block = documentBlocks[blockIdx];
      if (!block) continue;
      // Skip if already cached locally or currently fetching
      if (audioBuffersRef.current.has(block.id)) continue;
      if (synthesizingRef.current.has(block.id)) continue;

      // Fetch audio in background
      const fetchPromise = fetchAudioFromUrl(audioUrl, block.id);
      synthesizingRef.current.set(block.id, fetchPromise);
      fetchPromise.finally(() => {
        synthesizingRef.current.delete(block.id);
        bumpBlockStateVersion();
      });
    }
  }, [isServerMode, ttsWS.audioUrls, documentBlocks, fetchAudioFromUrl, bumpBlockStateVersion]);

  // Handle block changes and playback
  useEffect(() => {
    if (!documentBlocks || currentBlock === -1 || !isPlaying) {
      setIsSynthesizing(false);
      playingBlockRef.current = -1; // Reset when not playing
      return;
    }

    // For server mode: if WS is disconnected, we can still play cached blocks
    // Only skip if we need to synthesize AND WS is down
    const currentBlockId = documentBlocks[currentBlock]?.id;
    const hasCachedAudio = currentBlockId && audioBuffersRef.current.has(currentBlockId);

    if (isServerMode && !ttsWS.isConnected && !hasCachedAudio) {
      console.log(`[Playback] Waiting for WS connection (no cached audio for block ${currentBlock})...`);
      return;
    }

    const EVICT_THRESHOLD = 20; // Keep more buffers with parallel prefetch

    // Play/synthesize current block
    if (currentBlock < documentBlocks.length) {
      if (!currentBlockId) return;

      // Skip if we're already playing this block
      if (playingBlockRef.current === currentBlock) {
        return;
      }

      // Auto-advance if this block is marked as skipped (empty audio)
      if (ttsWS.blockStates.get(currentBlock) === "skipped") {
        console.log(`[Playback] Block ${currentBlock} is skipped, advancing to next`);
        playingBlockRef.current = currentBlock;
        setCurrentBlock(prev => {
          if (documentBlocks && prev < documentBlocks.length - 1) {
            return prev + 1;
          } else {
            setIsPlaying(false);
            return -1;
          }
        });
        return;
      }

      const audioData = audioBuffersRef.current.get(currentBlockId);
      if (audioData) {
        console.log(`[Playback] Cache HIT for block ${currentBlockId}, playing immediately`);
        playingBlockRef.current = currentBlock;
        setIsSynthesizing(false);
        setBlockStateVersion(v => v + 1); // Ensure progress bar reflects cached state
        playAudioBuffer(audioData);
      } else {
        // Show loading state while synthesizing current block
        console.log(`[Playback] Cache MISS for block ${currentBlockId}, synthesizing...`);
        setIsSynthesizing(true);
        playingBlockRef.current = currentBlock; // Mark as playing (waiting for synthesis)
        synthesizeBlock(currentBlockId).then(audioData => {
          // Check if this block is still the one we want (user may have clicked elsewhere)
          const stillCurrentBlock = documentBlocks[currentBlockRef.current]?.id === currentBlockId;
          if (!stillCurrentBlock) {
            console.log(`[Playback] Block ${currentBlockId} finished but user moved to different block, skipping playback`);
            return;
          }
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

    // Check buffer level and trigger refill if needed
    checkAndRefillBuffer();

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
  }, [currentBlock, isPlaying, documentBlocks, playAudioBuffer, synthesizeBlock, triggerPrefetchBatch, checkAndRefillBuffer, isServerMode, ttsWS.isConnected, ttsWS.blockStates]);


  // Helper: count resolved blocks ahead (cached or skipped)
  const countCachedAhead = useCallback((fromIdx: number): number => {
    if (!documentBlocks || documentBlocks.length === 0) return 0;
    let count = 0;
    for (let idx = fromIdx; idx < documentBlocks.length; idx++) {
      const block = documentBlocks[idx];
      const isSkipped = ttsWS.blockStates.get(idx) === "skipped";
      if (audioBuffersRef.current.has(block.id) || isSkipped) {
        count++;
      } else {
        break; // Stop at first gap
      }
    }
    return count;
  }, [documentBlocks, ttsWS.blockStates]);

  const handlePlay = async () => {
    if (isPlaying || isBuffering) return;

    if (audioContextRef.current?.state === 'suspended') {
      await audioContextRef.current.resume();
    }

    // Determine starting position
    const startBlock = currentBlock === -1 ? 0 : currentBlock;
    if (currentBlock === -1) {
      setCurrentBlock(0);
      setAudioProgress(0);
      blockStartTimeRef.current = 0;
    }

    const isServer = isServerSideModel(voiceSelection.model);

    // Browser mode: start immediately (single-threaded WASM, pre-buffering would add latency)
    // Server mode: check buffer and potentially enter buffering state first
    if (!isServer) {
      console.log(`[Playback] Browser mode, starting immediately`);
      setIsPlaying(true);
      return;
    }

    // Server mode: check if we have enough cached blocks to start playing
    // For short documents, don't require more blocks than exist
    const cachedAhead = countCachedAhead(startBlock);
    const remainingBlocks = documentBlocks.length - startBlock;
    const requiredBuffer = Math.min(MIN_BUFFER_TO_START, remainingBlocks);

    if (cachedAhead >= requiredBuffer) {
      console.log(`[Playback] Buffer ready: ${cachedAhead} blocks cached, starting playback`);
      setIsPlaying(true);
    } else {
      console.log(`[Playback] Buffer insufficient: ${cachedAhead}/${requiredBuffer} blocks, entering buffering state`);
      setIsBuffering(true);

      // Request initial batch for server mode
      if (ttsWS.isConnected) {
        triggerPrefetchBatch(startBlock, BATCH_SIZE);
      }
    }
  };

  const handlePause = () => {
    setIsPlaying(false);
    audioPlayerRef.current?.pause();
    // Note: Don't cancel buffering/prefetch - let it continue in background
  };

  // Keep refs updated for keyboard handler (avoids stale closures)
  handlePlayRef.current = handlePlay;
  handlePauseRef.current = handlePause;

  // Cancel buffering - stop waiting, return to stopped state
  const handleCancelBuffering = () => {
    console.log(`[Playback] Canceling buffering`);
    setIsBuffering(false);
    setIsPlaying(false);
    setIsSynthesizing(false);
    audioPlayerRef.current?.stop();

    // Send cursor_moved to evict queued blocks in backend
    if (documentId && isServerSideModel(voiceSelection.model)) {
      ttsWS.moveCursor(documentId, currentBlockRef.current);
    }

    // Clear local synthesis tracking
    synthesizingRef.current.clear();
    prefetchedUpToRef.current = -1;
  };

  // Legacy cancel handler - now redirects to cancel buffering
  const handleCancelSynthesis = handleCancelBuffering;

  const handleSkipBack = () => {
    // Stop current audio
    audioPlayerRef.current?.stop();

    // Don't modify progress if we're in an invalid state
    if (currentBlock < 0 || !documentBlocks.length) {
      console.log('[SkipBack] Invalid state, currentBlock:', currentBlock);
      return;
    }

    if (currentBlock > 0) {
      // Calculate progress up to the new block
      const newBlock = currentBlock - 1;
      let progressMs = 0;
      for (let i = 0; i < newBlock; i++) {
        const blockData = audioBuffersRef.current.get(documentBlocks[i].id);
        progressMs += blockData?.duration_ms ?? documentBlocks[i].est_duration_ms ?? 0;
      }
      console.log('[SkipBack] Going to block', newBlock, 'progress:', progressMs);
      blockStartTimeRef.current = progressMs;
      setAudioProgress(progressMs);
      setCurrentBlock(newBlock);
      scrollToBlock(newBlock);
    } else {
      // At first block (currentBlock === 0) - restart from beginning
      console.log('[SkipBack] At first block, restarting');
      blockStartTimeRef.current = 0;
      setAudioProgress(0);
      scrollToBlock(0);
      if (isPlaying && documentBlocks.length > 0) {
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
      scrollToBlock(newBlock);
    }
  };

  // Memoized to prevent StructuredDocumentView re-renders from audioProgress updates
  // Uses currentBlockRef instead of currentBlock to keep callback stable
  // Note: Uses ttsWS.moveCursor directly (stable ref) instead of ttsWS object to prevent
  // cascading re-renders when WS state (blockStates/audioUrls) changes during playback
  const handleBlockChange = useCallback((newBlock: number) => {
    if (newBlock === currentBlockRef.current) return;
    if (!documentBlocks || newBlock < 0 || newBlock >= documentBlocks.length) {
      console.warn(`[Playback] Invalid block ${newBlock} (have ${documentBlocks?.length ?? 0} blocks)`);
      return;
    }

    console.log(`[Playback] Jumping to block ${newBlock}`);
    audioPlayerRef.current?.stop();

    // Notify backend to evict blocks outside new cursor window
    if (documentId && isServerSideModel(voiceSelection.model)) {
      ttsWS.moveCursor(documentId, newBlock);
    }

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
  }, [documentBlocks, documentId, voiceSelection.model, ttsWS.moveCursor]);

  // Handle click on structured document block (by audio_block_idx)
  // Memoized to prevent StructuredDocumentView re-renders from audioProgress updates
  const handleDocumentBlockClick = useCallback((audioBlockIdx: number) => {
    handleBlockChange(audioBlockIdx);
  }, [handleBlockChange]);

  const handleVolumeChange = useCallback((newVolume: number) => {
    setVolume(newVolume);
  }, []);

  const handleSpeedChange = useCallback((newSpeed: number) => {
    setPlaybackSpeed(newSpeed);
  }, []);

  const handleTitleChange = useCallback(async (newTitle: string) => {
    if (!documentId) return;
    try {
      await api.patch(`/v1/documents/${documentId}`, { title: newTitle });
      setDocument(prev => prev ? { ...prev, title: newTitle } : prev);
      // Notify sidebar to update its document list
      window.dispatchEvent(new CustomEvent('document-title-changed', {
        detail: { documentId, title: newTitle }
      }));
    } catch (err) {
      console.error("Failed to update title:", err);
      // Revert to original title on error
      setDocument(prev => prev ? { ...prev } : prev);
      const errorMessage = err instanceof AxiosError && err.response?.status === 422
        ? "Title is too long (max 500 characters)"
        : "Failed to update title";
      alert(errorMessage);
    }
  }, [api, documentId]);

  // Memoize progressBarValues to prevent SoundControl re-renders when unrelated state changes
  const progressBarValues = useMemo(() => ({
    estimated_ms: actualTotalDuration > 0 ? actualTotalDuration : estimated_ms,
    numberOfBlocks,
    currentBlock: currentBlock >= 0 ? currentBlock : 0,
    setCurrentBlock: handleBlockChange,
    onBlockHover: handleBlockHover,
    audioProgress,
    blockStates,
  }), [actualTotalDuration, estimated_ms, numberOfBlocks, currentBlock, handleBlockChange, handleBlockHover, audioProgress, blockStates]);

  if (isLoading) {
    return (
      <div className="flex grow items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    if (error === "not_found") {
      return (
        <div className="flex min-h-[80vh] flex-col items-center justify-center gap-6 text-muted-foreground">
          <FileQuestion className="h-20 w-20" />
          <h1 className="text-2xl font-semibold text-foreground">Document not found</h1>
          <p className="text-base">This document may have been deleted or the link is incorrect.</p>
          <Link to="/" className="text-lg text-primary hover:underline">
            ← Back to home
          </Link>
        </div>
      );
    }
    return (
      <div className="flex grow items-center justify-center text-destructive">
        {error}
      </div>
    );
  }

  return (
    <div className="flex grow">
      <StructuredDocumentView
        structuredContent={structuredContent}
        title={documentTitle}
        sourceUrl={sourceUrl}
        markdownContent={markdownContent}
        onBlockClick={handleDocumentBlockClick}
        fallbackContent={fallbackContent}
        onTitleChange={handleTitleChange}
      />
      <SoundControl
        isPlaying={isPlaying}
        isBuffering={isBuffering}
        isSynthesizing={isSynthesizing}
        isReconnecting={ttsWS.isReconnecting}
        connectionError={ttsWS.connectionError}
        onPlay={handlePlay}
        onPause={handlePause}
        onCancelSynthesis={handleCancelSynthesis}
        onSkipBack={handleSkipBack}
        onSkipForward={handleSkipForward}
        progressBarValues={progressBarValues}
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
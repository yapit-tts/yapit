import { useSyncExternalStore, useRef, useState, useEffect, useLayoutEffect, useCallback, useMemo } from "react";
import { SoundControl } from '@/components/soundControl';
import { DocumentOutliner } from '@/components/documentOutliner';
import { OutlinerSidebar, OUTLINER_WIDTH } from '@/components/outlinerSidebar';
import { useOutliner } from '@/hooks/useOutliner';
import { useSidebar } from '@/components/ui/sidebar';
import { useFilteredPlayback } from '@/hooks/useFilteredPlayback';
import { useApi } from '@/api';
import { AudioLines, X } from "lucide-react";
import type { Section } from '@/lib/sectionIndex';
import type { PlaybackEngine, Block } from '@/lib/playbackEngine';
import type { VoiceSelection } from '@/lib/voiceSelection';
import type { UsePlaybackEngineReturn } from '@/hooks/usePlaybackEngine';

const POSITION_KEY_PREFIX = "yapit_playback_position_";

interface PlaybackOverlayProps {
  engine: PlaybackEngine;
  documentBlocks: Block[];
  sections: Section[];
  expandedSections: Set<string>;
  shouldShowOutliner: boolean;
  scrollBlockPosition: ScrollLogicalPosition;
  documentId: string | undefined;
  volume: number;
  onVolumeChange: (v: number) => void;
  playbackSpeed: number;
  onSpeedChange: (s: number) => void;
  voiceSelection: VoiceSelection;
  onVoiceChange: (v: VoiceSelection) => void;
  liveScrollTracking: boolean;
  ws: UsePlaybackEngineReturn['ws'];
  getServerTTSStatus: UsePlaybackEngineReturn['getServerTTSStatus'];
  getBrowserTTSStatus: UsePlaybackEngineReturn['getBrowserTTSStatus'];
  onSectionToggle: (sectionId: string) => void;
  onExpandAll: () => void;
  onCollapseAll: () => void;
  slugMap: Map<string, string>;
  // Ref bridges: overlay writes, shell reads
  scrollToBlockRef: React.MutableRefObject<(blockIdx: number, behavior?: ScrollBehavior) => void>;
  currentBlockRef: React.MutableRefObject<number>;
  handleBackToReadingRef: React.MutableRefObject<() => void>;
}

export function PlaybackOverlay({
  engine,
  documentBlocks,
  sections,
  expandedSections,
  shouldShowOutliner,
  scrollBlockPosition,
  documentId,
  volume,
  onVolumeChange,
  playbackSpeed,
  onSpeedChange,
  voiceSelection,
  onVoiceChange,
  liveScrollTracking,
  ws,
  getServerTTSStatus,
  getBrowserTTSStatus,
  onSectionToggle,
  onExpandAll,
  onCollapseAll,
  slugMap,
  scrollToBlockRef,
  currentBlockRef,
  handleBackToReadingRef,
}: PlaybackOverlayProps) {
  const snapshot = useSyncExternalStore(engine.subscribe, engine.getSnapshot);
  const { api, isAnonymous } = useApi();
  const sidebar = useSidebar();
  const outliner = useOutliner();

  const isPlaying = snapshot.status === "playing";
  const isBuffering = snapshot.status === "buffering";
  const currentBlock = snapshot.currentBlock;

  const serverTTS = getServerTTSStatus();
  const browserTTS = getBrowserTTSStatus();

  const estimated_ms = useMemo(
    () => documentBlocks.reduce((sum, b) => sum + (b.est_duration_ms || 0), 0),
    [documentBlocks],
  );

  // --- Ref bridges (shell's keyboard handler reads these) ---

  currentBlockRef.current = currentBlock;

  // --- DOM highlighting (imperative, no React state) ---

  const prevBlockIdxRef = useRef<number>(-1);
  const hoveredBlockRef = useRef<number | null>(null);
  const isDraggingProgressBarRef = useRef(false);
  const lastHoverScrollTimeRef = useRef<number>(0);

  const findElementsByAudioIdx = useCallback((idx: number) => {
    const innerSpans = window.document.querySelectorAll(`[data-audio-idx="${idx}"]`);
    if (innerSpans.length > 0) return innerSpans;
    return window.document.querySelectorAll(`[data-audio-block-idx="${idx}"]`);
  }, []);

  useLayoutEffect(() => {
    const ACTIVE_BLOCK_CLASS = "audio-block-active";
    if (prevBlockIdxRef.current >= 0) {
      findElementsByAudioIdx(prevBlockIdxRef.current).forEach(el => el.classList.remove(ACTIVE_BLOCK_CLASS));
    }
    if (currentBlock >= 0) {
      findElementsByAudioIdx(currentBlock).forEach(el => el.classList.add(ACTIVE_BLOCK_CLASS));
    }
    prevBlockIdxRef.current = currentBlock;
  }, [currentBlock, findElementsByAudioIdx]);

  const handleBlockHover = useCallback((idx: number | null, isDragging: boolean) => {
    const prevHovered = hoveredBlockRef.current;
    hoveredBlockRef.current = idx;
    isDraggingProgressBarRef.current = isDragging;
    const HOVER_BLOCK_CLASS = "audio-block-hovered";

    if (prevHovered !== null && prevHovered !== idx) {
      findElementsByAudioIdx(prevHovered).forEach(el => el.classList.remove(HOVER_BLOCK_CLASS));
    }
    if (idx !== null && idx !== currentBlock) {
      findElementsByAudioIdx(idx).forEach(el => el.classList.add(HOVER_BLOCK_CLASS));
    }
    if (idx === null || idx === currentBlock) {
      if (prevHovered !== null) {
        findElementsByAudioIdx(prevHovered).forEach(el => el.classList.remove(HOVER_BLOCK_CLASS));
      }
    }

    if (isDragging && idx !== null && idx !== currentBlock) {
      const SCROLL_THROTTLE_MS = 500;
      const now = Date.now();
      if (now - lastHoverScrollTimeRef.current >= SCROLL_THROTTLE_MS) {
        const element = findElementsByAudioIdx(idx)[0];
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
  }, [findElementsByAudioIdx, currentBlock]);

  // --- Position save ---

  const documentIdRef = useRef(documentId);
  documentIdRef.current = documentId;
  const isAnonymousRef = useRef(isAnonymous);
  isAnonymousRef.current = isAnonymous;

  useEffect(() => {
    if (!documentIdRef.current || currentBlock < 0) return;
    localStorage.setItem(
      POSITION_KEY_PREFIX + documentIdRef.current,
      JSON.stringify({ block: currentBlock, progressMs: engine.getBlockStartTime() }),
    );
    if (!isAnonymousRef.current) {
      api.patch(`/v1/documents/${documentIdRef.current}/position`, {
        block_idx: currentBlock,
      }).catch(() => {});
    }
  }, [currentBlock, api, engine]);

  // --- Scroll handling ---

  const [isScrollDetached, setIsScrollDetached] = useState(false);
  const [backToReadingDismissed, setBackToReadingDismissed] = useState(false);
  const scrollCooldownRef = useRef(false);
  const scrollCooldownTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const scrollToBlock = useCallback((blockIdx: number, behavior: ScrollBehavior = "smooth") => {
    if (blockIdx < 0) return;
    scrollCooldownRef.current = true;
    if (scrollCooldownTimerRef.current) clearTimeout(scrollCooldownTimerRef.current);
    const element = findElementsByAudioIdx(blockIdx)[0];
    if (element) element.scrollIntoView({ behavior, block: scrollBlockPosition });
    scrollCooldownTimerRef.current = setTimeout(() => { scrollCooldownRef.current = false; }, 1200);
  }, [findElementsByAudioIdx, scrollBlockPosition]);

  scrollToBlockRef.current = scrollToBlock;

  // Preview scroll position change immediately
  useEffect(() => {
    if (currentBlock >= 0) scrollToBlock(currentBlock);
  }, [scrollBlockPosition]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (currentBlock < 0 || !isPlaying) return;
    if (!liveScrollTracking || isScrollDetached) return;
    if (scrollCooldownRef.current) return;
    scrollToBlock(currentBlock);
  }, [currentBlock, liveScrollTracking, isScrollDetached, scrollToBlock, isPlaying]);

  useEffect(() => {
    if (!isPlaying || !liveScrollTracking || isScrollDetached || currentBlock < 0) return;
    if (scrollCooldownRef.current) return;
    scrollToBlock(currentBlock);
  }, [isPlaying, liveScrollTracking, isScrollDetached, currentBlock, scrollToBlock]);

  useEffect(() => {
    const handleScroll = () => {
      if (scrollCooldownRef.current) return;
      if (!isPlaying || !liveScrollTracking) return;
      if (isScrollDetached) return;
      setIsScrollDetached(true);
      setBackToReadingDismissed(false);
    };
    window.addEventListener('scroll', handleScroll, { passive: true });
    return () => window.removeEventListener('scroll', handleScroll);
  }, [liveScrollTracking, isScrollDetached, isPlaying]);

  useEffect(() => {
    if (isPlaying && isScrollDetached) {
      setIsScrollDetached(false);
      scrollToBlock(currentBlock);
    }
  }, [isPlaying]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleBackToReading = useCallback(() => {
    setIsScrollDetached(false);
    scrollToBlock(currentBlock, "smooth");
  }, [currentBlock, scrollToBlock]);

  handleBackToReadingRef.current = handleBackToReading;

  // --- MediaSession playback state + position ---

  useEffect(() => {
    if (!("mediaSession" in navigator)) return;
    navigator.mediaSession.playbackState = isPlaying ? "playing" : "paused";
    if (snapshot.totalDuration > 0) {
      try {
        const durationSec = snapshot.totalDuration / 1000;
        const positionSec = Math.min(snapshot.audioProgress / 1000, durationSec);
        navigator.mediaSession.setPositionState({
          duration: durationSec,
          playbackRate: playbackSpeed,
          position: positionSec,
        });
      } catch { /* setPositionState can throw on invalid values */ }
    }
  }, [isPlaying, snapshot.audioProgress, snapshot.totalDuration, playbackSpeed]);

  // --- Progress bar values ---

  const handleBlockChange = useCallback((newBlock: number) => {
    engine.seekToBlock(newBlock);
  }, [engine]);

  const filteredPlayback = useFilteredPlayback(
    documentBlocks,
    sections,
    expandedSections,
    snapshot.blockStates,
    currentBlock,
  );

  const progressBarValues = useMemo(() => {
    if (shouldShowOutliner) {
      return {
        estimated_ms: filteredPlayback.filteredDuration,
        numberOfBlocks: filteredPlayback.filteredBlockCount,
        currentBlock: filteredPlayback.visualCurrentBlock ?? 0,
        setCurrentBlock: handleBlockChange,
        onBlockHover: handleBlockHover,
        audioProgress: filteredPlayback.filteredElapsedMs,
        blockStates: filteredPlayback.filteredBlockStates,
        visualToAbsolute: filteredPlayback.visualToAbsolute,
      };
    }
    return {
      estimated_ms: snapshot.totalDuration > 0 ? snapshot.totalDuration : estimated_ms,
      numberOfBlocks: documentBlocks.length,
      currentBlock: currentBlock >= 0 ? currentBlock : 0,
      setCurrentBlock: handleBlockChange,
      onBlockHover: handleBlockHover,
      audioProgress: snapshot.audioProgress,
      blockStates: snapshot.blockStates,
    };
  }, [shouldShowOutliner, filteredPlayback, snapshot, estimated_ms, documentBlocks.length, currentBlock, handleBlockChange, handleBlockHover]);

  // --- Outliner navigation ---

  const handleOutlinerNavigate = useCallback((blockIdx: number) => {
    engine.seekToBlock(blockIdx);
    scrollToBlock(blockIdx);
    const section = sections.find(s => s.startBlockIdx === blockIdx)
      ?? sections.flatMap(s => s.subsections).find(s => s.blockIdx === blockIdx);
    const slug = section ? slugMap.get(section.id) : undefined;
    if (slug) {
      history.replaceState(null, "", `#${slug}`);
    }
  }, [engine, scrollToBlock, sections, slugMap]);

  // --- Render ---

  return (
    <>
      {isPlaying && isScrollDetached && !backToReadingDismissed && (
        <div
          className="fixed z-50 flex justify-center pointer-events-none transition-[left,right] duration-200 ease-linear"
          style={{
            bottom: "calc(var(--playbar-height, 120px) + 80px)",
            left: sidebar.isMobile || sidebar.state === "collapsed" ? 0 : "var(--sidebar-width)",
            right: sidebar.isMobile || outliner.state !== "expanded" ? 0 : OUTLINER_WIDTH,
          }}
        >
          <div className="flex items-center gap-2 bg-background/95 backdrop-blur-sm border border-border rounded-full px-4 py-2 shadow-lg pointer-events-auto">
            <button onClick={handleBackToReading} className="flex items-center gap-2 text-sm font-medium text-foreground hover:text-primary transition-colors">
              <AudioLines className="h-4 w-4 text-primary" />
              Back to Reading
            </button>
            <button onClick={() => setBackToReadingDismissed(true)} className="p-1 text-muted-foreground hover:text-foreground transition-colors" aria-label="Dismiss">
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}
      <SoundControl
        isPlaying={isPlaying}
        isBuffering={isBuffering}
        isSynthesizing={snapshot.isSynthesizingCurrent}
        isReconnecting={ws.isReconnecting}
        connectionError={ws.connectionError}
        onPlay={() => engine.play()}
        onPause={() => engine.pause()}
        onCancelSynthesis={() => engine.stop()}
        onSkipBack={() => { engine.skipBack(); scrollToBlockRef.current(engine.getSnapshot().currentBlock, "auto"); }}
        onSkipForward={() => { engine.skipForward(); scrollToBlockRef.current(engine.getSnapshot().currentBlock, "auto"); }}
        progressBarValues={progressBarValues}
        volume={volume}
        onVolumeChange={onVolumeChange}
        playbackSpeed={playbackSpeed}
        onSpeedChange={onSpeedChange}
        voiceSelection={voiceSelection}
        onVoiceChange={onVoiceChange}
        serverTTSError={serverTTS.error}
        serverTTSRecoverable={serverTTS.recoverable}
        browserTTSError={browserTTS.error}
        browserTTSDevice={browserTTS.device}
      />
      {shouldShowOutliner && (
        <OutlinerSidebar>
          <DocumentOutliner
            sections={sections}
            expandedSections={expandedSections}
            currentBlockIdx={currentBlock}
            onSectionToggle={onSectionToggle}
            onExpandAll={onExpandAll}
            onCollapseAll={onCollapseAll}
            onNavigate={handleOutlinerNavigate}
          />
        </OutlinerSidebar>
      )}
    </>
  );
}

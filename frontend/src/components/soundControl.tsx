import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Play, Pause, Volume2, SkipBack, SkipForward, Loader2, Square, WifiOff, ChevronUp, X } from "lucide-react";
import { useEffect, useState, useRef, useCallback, useMemo, memo } from "react";
import { useNavigate } from "react-router";
import { VoicePicker } from "@/components/voicePicker";
import { SettingsDialog } from "@/components/settingsDialog";
import { type VoiceSelection, setVoiceSelection, isInworldModel } from "@/lib/voiceSelection";
import { useSidebar } from "@/components/ui/sidebar";
import { useHasWebGPU } from "@/hooks/useWebGPU";

type BlockState = 'pending' | 'synthesizing' | 'cached';

// Hook for repeat-on-hold with acceleration (like volume buttons)
function useRepeatOnHold(callback: () => void, disabled?: boolean) {
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const currentDelayRef = useRef(400);
  const isActiveRef = useRef(false);
  const callbackRef = useRef(callback);

  // Keep callback ref up to date
  useEffect(() => {
    callbackRef.current = callback;
  }, [callback]);

  const INITIAL_DELAY = 400; // Wait before starting to repeat
  const START_INTERVAL = 350; // First repeat interval
  const MIN_INTERVAL = 75; // Fastest repeat interval
  const ACCELERATION = 0.92; // Multiply interval by this each repeat (gentler ramp)

  const stop = useCallback(() => {
    isActiveRef.current = false;
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
    currentDelayRef.current = START_INTERVAL;
  }, []);

  const startRepeating = useCallback(() => {
    if (disabled || !isActiveRef.current) return;

    const repeat = () => {
      if (!isActiveRef.current) return;
      callbackRef.current(); // Use ref to always get latest callback
      currentDelayRef.current = Math.max(MIN_INTERVAL, currentDelayRef.current * ACCELERATION);
      intervalRef.current = setTimeout(repeat, currentDelayRef.current) as unknown as ReturnType<typeof setInterval>;
    };

    timeoutRef.current = setTimeout(repeat, INITIAL_DELAY);
  }, [disabled]); // Remove callback from deps since we use ref

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (disabled) return;
    e.preventDefault();
    isActiveRef.current = true;
    callbackRef.current(); // Use ref
    startRepeating();
  }, [disabled, startRepeating]);

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    if (disabled) return;
    e.preventDefault();
    isActiveRef.current = true;
    callbackRef.current(); // Use ref
    startRepeating();
  }, [disabled, startRepeating]);

  // Cleanup on unmount
  useEffect(() => stop, [stop]);

  return {
    onMouseDown: handleMouseDown,
    onMouseUp: stop,
    onMouseLeave: stop,
    onTouchStart: handleTouchStart,
    onTouchEnd: stop,
    onTouchCancel: stop,
  };
}

// Switch to smooth gradient visualization for documents with many blocks
const SMOOTH_THRESHOLD = 200;

// Minimum width for collapsed sections (in pixels)
const COLLAPSED_SECTION_WIDTH = 4;

interface ProgressBarProps {
  blockStates: BlockState[];
  currentBlock: number;
  onBlockClick: (idx: number) => void;
  onBlockHover?: (idx: number | null, isDragging: boolean) => void;
}

interface SectionedProgressBarProps extends ProgressBarProps {
  sections: Section[];
  expandedSections: Set<string>;
  onSectionExpand: (sectionId: string) => void;
}

// Progress bar with section gaps for collapsed sections
function SectionedProgressBar({
  blockStates,
  currentBlock,
  onBlockClick,
  // onBlockHover, // TODO: implement hover handling for sectioned bar
  sections,
  expandedSections,
  onSectionExpand,
}: SectionedProgressBarProps) {
  const barRef = useRef<HTMLDivElement>(null);

  // Calculate total expanded blocks for width calculation
  const expandedBlockCount = useMemo(() => {
    return sections.reduce((sum, section) => {
      if (expandedSections.has(section.id)) {
        return sum + (section.endBlockIdx - section.startBlockIdx + 1);
      }
      return sum;
    }, 0);
  }, [sections, expandedSections]);

  // const collapsedCount = sections.length - expandedSections.size; // TODO: use for visual indicators

  // Build gradient for a single section
  const buildSectionGradient = useCallback((section: Section) => {
    const stateToColor = (state: BlockState, isCurrent: boolean) => {
      if (isCurrent) return 'var(--primary)';
      if (state === 'cached') return 'var(--muted)';
      if (state === 'synthesizing') return 'oklch(0.85 0.12 90 / 0.5)';
      return 'color-mix(in oklch, var(--muted-warm) 50%, transparent)';
    };

    const sectionBlocks = section.endBlockIdx - section.startBlockIdx + 1;
    if (sectionBlocks === 0) return 'transparent';

    const stops: string[] = [];
    let currentState = blockStates[section.startBlockIdx] ?? 'pending';
    let currentIsCurrent = currentBlock === section.startBlockIdx;
    let startPct = 0;

    for (let i = section.startBlockIdx + 1; i <= section.endBlockIdx + 1; i++) {
      const isCurrent = i === currentBlock;
      const state = i <= section.endBlockIdx ? (blockStates[i] ?? 'pending') : currentState;
      const nextIsCurrent = i <= section.endBlockIdx ? i === currentBlock : false;

      if (i > section.endBlockIdx || state !== currentState || isCurrent !== currentIsCurrent) {
        const relativeIdx = i - section.startBlockIdx;
        const endPct = (relativeIdx / sectionBlocks) * 100;
        const color = stateToColor(currentState, currentIsCurrent);
        stops.push(`${color} ${startPct}%`);
        stops.push(`${color} ${endPct}%`);
        startPct = endPct;
        currentState = state;
        currentIsCurrent = nextIsCurrent;
      }
    }

    return `linear-gradient(to right, ${stops.join(', ')})`;
  }, [blockStates, currentBlock]);

  // Handle click on expanded section
  const handleSectionClick = useCallback((section: Section, e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const pct = Math.max(0, Math.min(1, x / rect.width));
    const sectionBlocks = section.endBlockIdx - section.startBlockIdx + 1;
    const relativeIdx = Math.min(sectionBlocks - 1, Math.floor(pct * sectionBlocks));
    const absoluteIdx = section.startBlockIdx + relativeIdx;
    onBlockClick(absoluteIdx);
  }, [onBlockClick]);

  // Current position indicator
  const currentSectionIdx = useMemo(() => {
    return sections.findIndex(s => currentBlock >= s.startBlockIdx && currentBlock <= s.endBlockIdx);
  }, [sections, currentBlock]);

  return (
    <div
      ref={barRef}
      className="w-full h-2 rounded-full flex overflow-hidden bg-muted/30"
    >
      {sections.map((section, idx) => {
        const isExpanded = expandedSections.has(section.id);
        const sectionBlocks = section.endBlockIdx - section.startBlockIdx + 1;
        const isCurrent = idx === currentSectionIdx;

        if (isExpanded) {
          // Expanded section: show full gradient
          const gradient = buildSectionGradient(section);
          const widthPct = expandedBlockCount > 0
            ? (sectionBlocks / expandedBlockCount) * 100
            : 0;

          // Calculate current position within section
          const currentPct = isCurrent && currentBlock >= section.startBlockIdx
            ? ((currentBlock - section.startBlockIdx) / sectionBlocks) * 100
            : null;

          return (
            <div
              key={section.id}
              className="relative h-full cursor-pointer transition-all duration-200"
              style={{
                flex: `${widthPct} 0 0%`,
                background: gradient,
                minWidth: '8px',
              }}
              onClick={(e) => handleSectionClick(section, e)}
            >
              {/* Current position indicator */}
              {currentPct !== null && (
                <div
                  className="absolute top-0 bottom-0 w-0.5 bg-primary z-10"
                  style={{ left: `${currentPct}%` }}
                />
              )}
            </div>
          );
        } else {
          // Collapsed section: thin gap
          return (
            <div
              key={section.id}
              className="h-full cursor-pointer transition-all duration-200 hover:bg-muted-foreground/30"
              style={{
                width: `${COLLAPSED_SECTION_WIDTH}px`,
                flexShrink: 0,
                background: isCurrent ? 'var(--primary)' : 'var(--muted-foreground)',
                opacity: isCurrent ? 0.8 : 0.3,
              }}
              onClick={() => onSectionExpand(section.id)}
              title="Click to expand section"
            />
          );
        }
      })}
    </div>
  );
}

// Smooth gradient visualization for large documents
function SmoothProgressBar({ blockStates, currentBlock, onBlockClick, onBlockHover }: ProgressBarProps) {
  const barRef = useRef<HTMLDivElement>(null);
  const numBlocks = blockStates.length;

  // Drag state (local)
  const [isDragging, setIsDragging] = useState(false);
  const [seekPosition, setSeekPosition] = useState<number | null>(null); // Block index being seeked to
  const dragStartXRef = useRef<number | null>(null);
  const DRAG_THRESHOLD = 5; // pixels before we consider it a drag vs click

  const getBlockFromX = useCallback((clientX: number) => {
    if (!barRef.current) return 0;
    const rect = barRef.current.getBoundingClientRect();
    const x = clientX - rect.left;
    const pct = Math.max(0, Math.min(1, x / rect.width));
    return Math.min(numBlocks - 1, Math.floor(pct * numBlocks));
  }, [numBlocks]);

  // Get X coordinate from either mouse or touch event
  const getClientX = (e: React.MouseEvent | React.TouchEvent): number => {
    if ('touches' in e) {
      return e.touches[0]?.clientX ?? e.changedTouches[0]?.clientX ?? 0;
    }
    return e.clientX;
  };

  const handleStart = (clientX: number) => {
    dragStartXRef.current = clientX;
  };

  const handleMove = (clientX: number) => {
    const blockIdx = getBlockFromX(clientX);

    let currentlyDragging = isDragging;
    if (dragStartXRef.current !== null && !isDragging) {
      const moved = Math.abs(clientX - dragStartXRef.current) > DRAG_THRESHOLD;
      if (moved) {
        setIsDragging(true);
        currentlyDragging = true;
      }
    }

    setSeekPosition(blockIdx);
    onBlockHover?.(blockIdx, currentlyDragging);
  };

  const handleEnd = (clientX: number) => {
    const blockIdx = getBlockFromX(clientX);
    onBlockClick(blockIdx);
    setIsDragging(false);
    setSeekPosition(null);
    dragStartXRef.current = null;
    onBlockHover?.(null, false);
  };

  const handleCancel = () => {
    setIsDragging(false);
    setSeekPosition(null);
    dragStartXRef.current = null;
    onBlockHover?.(null, false);
  };

  // Track last hover position to avoid unnecessary updates
  const lastHoverBlockRef = useRef<number | null>(null);

  // Mouse events
  const handleMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    handleStart(e.clientX);
  };
  const handleMouseMove = (e: React.MouseEvent) => {
    if (dragStartXRef.current !== null) {
      handleMove(e.clientX);
    } else {
      // Just hovering - show indicator but only update if block changed
      const blockIdx = getBlockFromX(e.clientX);
      if (blockIdx !== lastHoverBlockRef.current) {
        lastHoverBlockRef.current = blockIdx;
        setSeekPosition(blockIdx);
        onBlockHover?.(blockIdx, false);
      }
    }
  };
  const handleMouseUp = (e: React.MouseEvent) => {
    handleEnd(e.clientX);
  };
  const handleMouseLeave = () => {
    lastHoverBlockRef.current = null;
    setSeekPosition(null);
    if (!isDragging) {
      onBlockHover?.(null, false);
    }
  };

  // Touch events
  const handleTouchStart = (e: React.TouchEvent) => {
    e.preventDefault();
    handleStart(getClientX(e));
  };
  const handleTouchMove = (e: React.TouchEvent) => {
    e.preventDefault();
    handleMove(getClientX(e));
  };
  const handleTouchEnd = (e: React.TouchEvent) => {
    handleEnd(getClientX(e));
  };

  // Build CSS gradient from block states - memoized to avoid rebuilding on every hover
  const gradient = useMemo(() => {
    if (numBlocks === 0) return 'transparent';

    // State colors: pending=warm brown, cached=light green, current=solid green
    const stateToColor = (state: BlockState, isCurrent: boolean) => {
      if (isCurrent) return 'var(--primary)';
      if (state === 'cached') return 'var(--muted)'; // cached - light green
      if (state === 'synthesizing') return 'oklch(0.85 0.12 90 / 0.5)'; // muted yellow
      return 'color-mix(in oklch, var(--muted-warm) 50%, transparent)'; // pending - warm tan
    };

    const stops: string[] = [];
    let currentState = blockStates[0];
    let currentIsCurrent = currentBlock === 0;
    let startPct = 0;

    for (let i = 1; i <= numBlocks; i++) {
      const isCurrent = i === currentBlock;
      const state = i < numBlocks ? blockStates[i] : currentState;
      const nextIsCurrent = i < numBlocks ? i === currentBlock : false;

      // Check if we need to close the current segment
      if (i === numBlocks || state !== currentState || isCurrent !== currentIsCurrent) {
        const endPct = (i / numBlocks) * 100;
        const color = stateToColor(currentState, currentIsCurrent);
        stops.push(`${color} ${startPct}%`);
        stops.push(`${color} ${endPct}%`);
        startPct = endPct;
        currentState = state;
        currentIsCurrent = nextIsCurrent;
      }
    }

    return `linear-gradient(to right, ${stops.join(', ')})`;
  }, [blockStates, currentBlock, numBlocks]);

  const currentPct = numBlocks > 0 ? (currentBlock / numBlocks) * 100 : 0;

  return (
    <div
      ref={barRef}
      className="flex-1 h-10 md:h-5 rounded overflow-hidden cursor-pointer relative touch-none"
      style={{ background: gradient }}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseLeave}
      onTouchStart={handleTouchStart}
      onTouchMove={handleTouchMove}
      onTouchEnd={handleTouchEnd}
      onTouchCancel={handleCancel}
      role="slider"
      aria-valuemin={1}
      aria-valuemax={numBlocks}
      aria-valuenow={currentBlock + 1}
      tabIndex={0}
    >
      {/* Current position indicator - primary green */}
      <div
        className="absolute top-0 bottom-0 w-1 pointer-events-none"
        style={{
          left: `${currentPct}%`,
          transform: 'translateX(-50%)',
          backgroundColor: 'var(--primary)',
          boxShadow: '0 0 6px oklch(0.55 0.1 133.7 / 0.8)',
        }}
      />
      {/* Seek position indicator - same width as current position */}
      {seekPosition !== null && seekPosition !== currentBlock && (
        <div
          className="absolute top-0 bottom-0 w-1 pointer-events-none"
          style={{
            left: `${(seekPosition / numBlocks) * 100}%`,
            transform: 'translateX(-50%)',
            backgroundColor: 'var(--primary)',
            boxShadow: '0 0 6px oklch(0.55 0.1 133.7 / 0.8)',
          }}
        />
      )}
    </div>
  );
}

// Individual block visualization for smaller documents
function BlockyProgressBar({ blockStates, currentBlock, onBlockClick, onBlockHover }: ProgressBarProps) {
  const barRef = useRef<HTMLDivElement>(null);
  const numBlocks = blockStates.length;

  // Drag state
  const [isDragging, setIsDragging] = useState(false);
  const [seekPosition, setSeekPosition] = useState<number | null>(null);
  const dragStartXRef = useRef<number | null>(null);
  const DRAG_THRESHOLD = 5;

  const getBlockFromX = useCallback((clientX: number) => {
    if (!barRef.current) return 0;
    const rect = barRef.current.getBoundingClientRect();
    const x = clientX - rect.left;
    const pct = Math.max(0, Math.min(1, x / rect.width));
    return Math.min(numBlocks - 1, Math.floor(pct * numBlocks));
  }, [numBlocks]);

  if (numBlocks === 0) {
    return <div className="flex-1 h-10 md:h-5 bg-muted rounded" />;
  }

  // Get X coordinate from touch event
  const getClientX = (e: React.TouchEvent): number => {
    return e.touches[0]?.clientX ?? e.changedTouches[0]?.clientX ?? 0;
  };

  const handleStart = (clientX: number) => {
    dragStartXRef.current = clientX;
  };

  const handleMove = (clientX: number) => {
    const blockIdx = getBlockFromX(clientX);
    let currentlyDragging = isDragging;
    if (dragStartXRef.current !== null && !isDragging) {
      const moved = Math.abs(clientX - dragStartXRef.current) > DRAG_THRESHOLD;
      if (moved) {
        setIsDragging(true);
        currentlyDragging = true;
      }
    }
    setSeekPosition(blockIdx);
    onBlockHover?.(blockIdx, currentlyDragging);
  };

  const handleEnd = (clientX: number) => {
    const blockIdx = getBlockFromX(clientX);
    onBlockClick(blockIdx);
    setIsDragging(false);
    setSeekPosition(null);
    dragStartXRef.current = null;
    onBlockHover?.(null, false);
  };

  const handleCancel = () => {
    setIsDragging(false);
    setSeekPosition(null);
    dragStartXRef.current = null;
    onBlockHover?.(null, false);
  };

  // Mouse events
  const handleMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    handleStart(e.clientX);
  };
  const handleMouseMove = (e: React.MouseEvent) => {
    if (dragStartXRef.current !== null) {
      handleMove(e.clientX);
    } else {
      const blockIdx = getBlockFromX(e.clientX);
      setSeekPosition(blockIdx);
      onBlockHover?.(blockIdx, false);
    }
  };
  const handleMouseUp = (e: React.MouseEvent) => handleEnd(e.clientX);
  const handleMouseLeave = () => {
    setSeekPosition(null);
    if (!isDragging) onBlockHover?.(null, false);
  };

  // Touch events
  const handleTouchStart = (e: React.TouchEvent) => {
    e.preventDefault();
    handleStart(getClientX(e));
  };
  const handleTouchMove = (e: React.TouchEvent) => {
    e.preventDefault();
    handleMove(getClientX(e));
  };
  const handleTouchEnd = (e: React.TouchEvent) => handleEnd(getClientX(e));

  return (
    <div
      ref={barRef}
      className="flex-1 flex items-center h-10 md:h-5 bg-muted/30 rounded overflow-hidden touch-none"
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseLeave}
      onTouchStart={handleTouchStart}
      onTouchMove={handleTouchMove}
      onTouchEnd={handleTouchEnd}
      onTouchCancel={handleCancel}
    >
      {blockStates.map((state, idx) => {
        const isCurrent = idx === currentBlock;
        const isSeekTarget = seekPosition === idx && seekPosition !== currentBlock;

        // State-based colors: pending=warm brown, cached=light green, current=solid green
        let bgColor = 'bg-muted-warm/50'; // pending - warm tan
        if (state === 'synthesizing') bgColor = 'bg-yellow-500/40'; // muted yellow, no pulse
        else if (state === 'cached') bgColor = 'bg-muted'; // cached - light green

        // Current block is solid green - the focal point
        if (isCurrent) {
          bgColor = 'bg-primary';
        }

        // Seek target gets green highlight (same as current playing)
        if (isSeekTarget) {
          bgColor = 'bg-primary';
        }

        return (
          <div
            key={idx}
            className={`h-full ${bgColor}`}
            style={{
              flex: '1 1 0',
              minWidth: 0,
              borderRight: idx < numBlocks - 1 ? '1px solid rgba(0,0,0,0.1)' : 'none',
            }}
          />
        );
      })}
    </div>
  );
}

// Section type for outliner integration
interface Section {
  id: string;
  startBlockIdx: number;
  endBlockIdx: number;
}

interface ProgressBarValues {
  estimated_ms: number | undefined;
  numberOfBlocks: number | undefined;
  currentBlock: number | undefined;
  setCurrentBlock: (value: number) => void;
  onBlockHover?: (idx: number | null, isDragging: boolean) => void;
  audioProgress: number;
  blockStates: BlockState[];
  // Section support for outliner gaps
  sections?: Section[];
  expandedSections?: Set<string>;
  onSectionExpand?: (sectionId: string) => void;
}

interface Props {
  isPlaying: boolean;
  isBuffering: boolean;
  isSynthesizing: boolean;
  isReconnecting?: boolean;
  connectionError?: string | null;
  blockError?: string | null;
  onPlay: () => void;
  onPause: () => void;
  onCancelSynthesis: () => void;
  onSkipBack: () => void;
  onSkipForward: () => void;
  progressBarValues: ProgressBarValues;
  volume: number;
  onVolumeChange: (value: number) => void;
  playbackSpeed: number;
  onSpeedChange: (value: number) => void;
  voiceSelection: VoiceSelection;
  onVoiceChange: (selection: VoiceSelection) => void;
}

function msToTime(duration: number | undefined): string {
  if (duration == undefined || duration <= 0) return "0:00";

  const totalSeconds = Math.floor(duration / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  if (hours > 0) {
    return `${hours}:${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`;
  }
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

const SoundControl = memo(function SoundControl({
  isPlaying,
  isBuffering,
  isSynthesizing,
  isReconnecting,
  connectionError,
  blockError,
  onPlay,
  onPause,
  onCancelSynthesis,
  onSkipBack,
  onSkipForward,
  progressBarValues,
  volume,
  onVolumeChange,
  playbackSpeed,
  onSpeedChange,
  voiceSelection,
  onVoiceChange,
}: Props) {
  const { estimated_ms, numberOfBlocks, currentBlock, setCurrentBlock, onBlockHover, audioProgress, blockStates, sections, expandedSections, onSectionExpand } = progressBarValues;
  const [progressDisplay, setProgressDisplay] = useState("0:00");
  const [durationDisplay, setDurationDisplay] = useState("0:00");
  const [isHoveringSpinner, setIsHoveringSpinner] = useState(false);
  const [isMobileExpanded, setIsMobileExpanded] = useState(false);
  const [isHoveringProgressBar, setIsHoveringProgressBar] = useState(false);
  const [hoveredBlock, setHoveredBlock] = useState<number | null>(null);
  const [isDraggingProgressBar, setIsDraggingProgressBar] = useState(false);
  const navigate = useNavigate();

  // Detect quota exceeded error from either connection or block errors
  const usageLimitError = blockError?.includes("Usage limit exceeded") ? blockError :
                          connectionError?.includes("Usage limit exceeded") ? connectionError : null;
  const isUsingInworld = isInworldModel(voiceSelection.model);
  const isUsingKokoroServer = voiceSelection.model === "kokoro-server";

  // Banner dismissed state
  const [quotaDismissed, setQuotaDismissed] = useState(false);

  // Reset dismissed when voice model changes
  const prevModel = useRef(voiceSelection.model);
  useEffect(() => {
    if (voiceSelection.model !== prevModel.current) {
      setQuotaDismissed(false);
    }
    prevModel.current = voiceSelection.model;
  }, [voiceSelection.model]);

  const showQuotaBanner = usageLimitError && !quotaDismissed;

  // Wrap onPlay to reset dismissed state (so modal shows again on retry)
  const handlePlay = useCallback(() => {
    setQuotaDismissed(false);
    onPlay();
  }, [onPlay]);

  const handleSwitchToKokoro = useCallback(() => {
    const newSelection: VoiceSelection = {
      ...voiceSelection,
      model: "kokoro-server",
      voiceSlug: "af_heart",
    };
    onVoiceChange(newSelection);
    setVoiceSelection(newSelection);
    setQuotaDismissed(true);
  }, [voiceSelection, onVoiceChange]);

  const handleUpgradePlan = useCallback(() => {
    setQuotaDismissed(true);
    navigate("/subscription");
  }, [navigate]);

  const hasWebGPU = useHasWebGPU();

  const handleSwitchToLocal = useCallback(() => {
    const newSelection: VoiceSelection = {
      ...voiceSelection,
      model: "kokoro",
      voiceSlug: voiceSelection.voiceSlug.startsWith("af_") || voiceSelection.voiceSlug.startsWith("am_")
        ? voiceSelection.voiceSlug
        : "af_heart",
    };
    onVoiceChange(newSelection);
    setVoiceSelection(newSelection);
    setQuotaDismissed(true);
  }, [voiceSelection, onVoiceChange]);

  // Wrap onBlockHover to track hover state locally for display swap
  const handleBlockHover = useCallback((idx: number | null, isDragging: boolean) => {
    setHoveredBlock(idx);
    setIsHoveringProgressBar(idx !== null);
    setIsDraggingProgressBar(isDragging);
    onBlockHover?.(idx, isDragging);
  }, [onBlockHover]);

  // Get sidebar state for responsive positioning
  const { state: sidebarState, isMobile } = useSidebar();

  const numBlocks = numberOfBlocks ?? 0;

  // Long-press repeat with acceleration for skip buttons
  const skipBackProps = useRepeatOnHold(onSkipBack, (currentBlock ?? 0) <= 0 && !isPlaying);
  const skipForwardProps = useRepeatOnHold(onSkipForward, (currentBlock ?? 0) >= numBlocks - 1);

  // Hover handlers for play button spinner (show stop icon on hover during buffering)
  const handleSpinnerMouseEnter = useCallback(() => {
    if (isBuffering || isSynthesizing) setIsHoveringSpinner(true);
  }, [isBuffering, isSynthesizing]);
  const handleSpinnerMouseLeave = useCallback(() => setIsHoveringSpinner(false), []);

  useEffect(() => {
    setProgressDisplay(msToTime(audioProgress));
  }, [audioProgress]);

  useEffect(() => {
    setDurationDisplay(msToTime(estimated_ms));
  }, [estimated_ms]);

  const blockNum = (currentBlock ?? 0) + 1;

  // Playbar positioning: on mobile or collapsed sidebar, use full width; on desktop with expanded sidebar, offset by sidebar width
  const playbarPositionClass = isMobile || sidebarState === "collapsed"
    ? "left-0"
    : "left-[var(--sidebar-width)]";

  return (
    <div className={`fixed bottom-0 right-0 bg-background/80 backdrop-blur-lg border-t border-border p-4 transition-[left] duration-200 ease-linear ${playbarPositionClass}`}>
      {/* Usage limit banner */}
      {showQuotaBanner && (
        <div className="flex items-center justify-center gap-2 mb-3 py-2 px-4 bg-muted-warm rounded-lg text-sm border border-border">
          <span className="text-foreground font-medium">
            Voice quota reached
          </span>
          <span className="text-muted-foreground mx-1">·</span>
          {isUsingInworld && (
            <Button variant="ghost" size="sm" className="h-9 px-3" onClick={handleSwitchToKokoro}>
              Use Kokoro
            </Button>
          )}
          {hasWebGPU && isUsingKokoroServer && (
            <Button variant="ghost" size="sm" className="h-9 px-3" onClick={handleSwitchToLocal}>
              Use free local
            </Button>
          )}
          <Button variant="default" size="sm" className="h-9 px-3" onClick={handleUpgradePlan}>
            Upgrade
          </Button>
          <button
            onClick={() => setQuotaDismissed(true)}
            className="ml-2 p-2 min-w-[44px] min-h-[44px] flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-accent rounded-md transition-colors"
            aria-label="Dismiss"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* Playback controls */}
      <div className="flex items-center justify-center gap-4 mb-3">
        <Button
          variant="ghost"
          size="icon"
          disabled={(currentBlock ?? 0) <= 0 && !isPlaying}
          {...skipBackProps}
        >
          <SkipBack className="h-5 w-5" />
        </Button>
        <Button
          variant="secondary"
          size="lg"
          className="rounded-full w-14 h-14"
          onClick={isBuffering || isSynthesizing ? onCancelSynthesis : isPlaying ? onPause : handlePlay}
          onMouseEnter={handleSpinnerMouseEnter}
          onMouseLeave={handleSpinnerMouseLeave}
        >
          {isBuffering || isSynthesizing ? (
            isHoveringSpinner ? (
              <Square className="h-5 w-5 fill-current" />
            ) : (
              <Loader2 className="h-6 w-6 animate-spin" />
            )
          ) : isPlaying ? (
            <Pause className="h-6 w-6" />
          ) : (
            <Play className="h-6 w-6 ml-1" />
          )}
        </Button>
        <Button
          variant="ghost"
          size="icon"
          disabled={(currentBlock ?? 0) >= numBlocks - 1}
          {...skipForwardProps}
        >
          <SkipForward className="h-5 w-5" />
        </Button>
      </div>

      {/* Progress bar - smooth gradient for large docs, blocky for smaller ones */}
      {/* On hover: swap time displays with block numbers (current / total) */}
      <div className="flex items-center gap-4 max-w-2xl mx-auto">
        <span className="text-sm text-muted-foreground w-12 text-right tabular-nums">
          {isHoveringProgressBar
            ? (isDraggingProgressBar && hoveredBlock !== null ? hoveredBlock + 1 : blockNum)
            : progressDisplay}
        </span>
        {sections && expandedSections && onSectionExpand ? (
          <SectionedProgressBar
            blockStates={blockStates}
            currentBlock={currentBlock ?? 0}
            onBlockClick={setCurrentBlock}
            onBlockHover={handleBlockHover}
            sections={sections}
            expandedSections={expandedSections}
            onSectionExpand={onSectionExpand}
          />
        ) : blockStates.length > SMOOTH_THRESHOLD ? (
          <SmoothProgressBar
            blockStates={blockStates}
            currentBlock={currentBlock ?? 0}
            onBlockClick={setCurrentBlock}
            onBlockHover={handleBlockHover}
          />
        ) : (
          <BlockyProgressBar
            blockStates={blockStates}
            currentBlock={currentBlock ?? 0}
            onBlockClick={setCurrentBlock}
            onBlockHover={handleBlockHover}
          />
        )}
        <span className="text-sm text-muted-foreground w-12 tabular-nums">
          {isHoveringProgressBar ? numBlocks : durationDisplay}
        </span>
      </div>

      {/* Mobile: connection status + expand toggle */}
      {isMobile && (
        <div className="flex items-center justify-end gap-2 mt-2 max-w-2xl mx-auto">
          {(isReconnecting || (connectionError && !usageLimitError)) && (
            <span className={`flex items-center gap-1 text-xs ${connectionError ? 'text-destructive' : 'text-yellow-600'}`}>
              <WifiOff className="h-3 w-3" />
              {connectionError || 'Reconnecting...'}
            </span>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setIsMobileExpanded(!isMobileExpanded)}
            className="h-6 px-2"
          >
            <ChevronUp className={`h-4 w-4 transition-transform ${isMobileExpanded ? 'rotate-180' : ''}`} />
          </Button>
        </div>
      )}

      {/* Mobile expanded: voice, speed, volume - aligned columns */}
      {isMobile && isMobileExpanded && (
        <div className="mt-3 pt-3 border-t border-border/50 max-w-2xl mx-auto space-y-4">
          <div className="flex justify-center">
            <VoicePicker value={voiceSelection} onChange={onVoiceChange} />
          </div>
          {/* All rows use same column widths: w-12 left, flex-1 middle, w-12 right */}
          <div className="flex items-center gap-4">
            <span className="text-sm text-muted-foreground font-mono tabular-nums w-12 text-right flex-shrink-0">
              {playbackSpeed.toFixed(1)}x
            </span>
            <Slider
              value={[playbackSpeed]}
              min={0.5}
              max={3}
              step={0.1}
              onValueChange={(values) => onSpeedChange(values[0])}
              className="flex-1"
            />
            <div className="w-12 flex-shrink-0" />
          </div>
          <div className="flex items-center gap-4">
            <div className="w-12 flex-shrink-0 flex justify-end">
              <Volume2 className="h-5 w-5 text-muted-foreground" />
            </div>
            <Slider
              value={[volume]}
              max={100}
              step={1}
              onValueChange={(values) => onVolumeChange(values[0])}
              className="flex-1"
            />
            <div className="w-12 flex-shrink-0 flex justify-end">
              <SettingsDialog size="lg" />
            </div>
          </div>
        </div>
      )}

      {/* Desktop: horizontal layout with all controls */}
      {!isMobile && (
        <div className="flex items-center justify-between mt-3 max-w-xl mx-auto">
          <div className="flex items-center gap-4">
            <VoicePicker value={voiceSelection} onChange={onVoiceChange} />
            {(isReconnecting || (connectionError && !usageLimitError)) && (
              <span className={`flex items-center gap-1.5 text-sm ${connectionError ? 'text-destructive' : 'text-yellow-600'}`}>
                <WifiOff className="h-4 w-4" />
                {connectionError || 'Reconnecting...'}
              </span>
            )}
          </div>
          <div className="flex items-center gap-5">
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground font-mono tabular-nums w-12">
                {playbackSpeed.toFixed(1)}x
              </span>
              <Slider
                value={[playbackSpeed]}
                min={0.5}
                max={3}
                step={0.1}
                onValueChange={(values) => onSpeedChange(values[0])}
                className="w-32"
              />
            </div>
            <div className="flex items-center gap-2">
              <Volume2 className="h-5 w-5 text-muted-foreground" />
              <Slider
                value={[volume]}
                max={100}
                step={1}
                onValueChange={(values) => onVolumeChange(values[0])}
                className="w-32"
              />
            </div>
            <SettingsDialog />
          </div>
        </div>
      )}

    </div>
  );
});

export { SoundControl };

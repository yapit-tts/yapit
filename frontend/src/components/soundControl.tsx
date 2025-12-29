import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Play, Pause, Volume2, SkipBack, SkipForward, Loader2, Square, WifiOff, ChevronUp } from "lucide-react";
import { useEffect, useState, useRef, useCallback } from "react";
import { VoicePicker } from "@/components/voicePicker";
import { SettingsDialog } from "@/components/settingsDialog";
import { type VoiceSelection } from "@/lib/voiceSelection";
import { useSidebar } from "@/components/ui/sidebar";

type BlockState = 'pending' | 'synthesizing' | 'cached';

// Hook for repeat-on-hold with acceleration (like volume buttons)
function useRepeatOnHold(callback: () => void, disabled?: boolean) {
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const currentDelayRef = useRef(400);
  const isActiveRef = useRef(false);

  const INITIAL_DELAY = 400; // Wait before starting to repeat
  const START_INTERVAL = 400; // First repeat interval
  const MIN_INTERVAL = 50; // Fastest repeat interval
  const ACCELERATION = 0.85; // Multiply interval by this each repeat

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
      callback();
      currentDelayRef.current = Math.max(MIN_INTERVAL, currentDelayRef.current * ACCELERATION);
      intervalRef.current = setTimeout(repeat, currentDelayRef.current) as unknown as ReturnType<typeof setInterval>;
    };

    timeoutRef.current = setTimeout(repeat, INITIAL_DELAY);
  }, [callback, disabled]);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (disabled) return;
    e.preventDefault();
    isActiveRef.current = true;
    callback();
    startRepeating();
  }, [callback, disabled, startRepeating]);

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    if (disabled) return;
    e.preventDefault();
    isActiveRef.current = true;
    callback();
    startRepeating();
  }, [callback, disabled, startRepeating]);

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

interface ProgressBarProps {
  blockStates: BlockState[];
  currentBlock: number;
  onBlockClick: (idx: number) => void;
  onBlockHover?: (idx: number | null, isDragging: boolean) => void;
}

// Smooth gradient visualization for large documents
function SmoothProgressBar({ blockStates, currentBlock, onBlockClick, onBlockHover }: ProgressBarProps) {
  const barRef = useRef<HTMLDivElement>(null);
  const numBlocks = blockStates.length;

  // Drag state
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

  // Mouse events
  const handleMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    handleStart(e.clientX);
  };
  const handleMouseMove = (e: React.MouseEvent) => {
    if (dragStartXRef.current !== null) {
      handleMove(e.clientX);
    } else {
      // Just hovering - show indicator but don't trigger drag behavior
      const blockIdx = getBlockFromX(e.clientX);
      setSeekPosition(blockIdx);
      onBlockHover?.(blockIdx, false);
    }
  };
  const handleMouseUp = (e: React.MouseEvent) => {
    handleEnd(e.clientX);
  };
  const handleMouseLeave = () => {
    setSeekPosition(null); // Always clear indicator on leave
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

  // Build CSS gradient from block states
  // Group consecutive blocks with same state to reduce gradient complexity
  const buildGradient = () => {
    if (numBlocks === 0) return 'transparent';

    const stateToColor = (state: BlockState, isCurrent: boolean) => {
      if (isCurrent) return 'var(--primary)';
      if (state === 'cached') return 'color-mix(in oklch, var(--primary) 60%, transparent)';
      if (state === 'synthesizing') return 'oklch(0.75 0.15 85)'; // yellow
      return 'color-mix(in oklch, var(--muted) 50%, transparent)'; // pending
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
  };

  const gradient = buildGradient();
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
      {/* Current position indicator - bright green */}
      <div
        className="absolute top-0 bottom-0 w-1 pointer-events-none"
        style={{
          left: `${currentPct}%`,
          transform: 'translateX(-50%)',
          backgroundColor: 'oklch(0.55 0.15 145)',
          boxShadow: '0 0 6px oklch(0.55 0.15 145 / 0.8)',
        }}
      />
      {/* Seek position indicator - yellow/amber, only during drag */}
      {seekPosition !== null && seekPosition !== currentBlock && (
        <div
          className="absolute top-0 bottom-0 w-1.5 pointer-events-none"
          style={{
            left: `${(seekPosition / numBlocks) * 100}%`,
            transform: 'translateX(-50%)',
            backgroundColor: 'oklch(0.75 0.15 85)',
            boxShadow: '0 0 8px oklch(0.75 0.15 85 / 0.9)',
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

        // State-based colors
        let bgColor = 'bg-muted/50'; // pending - subtle gray
        if (state === 'synthesizing') bgColor = 'bg-yellow-500/70 animate-pulse';
        else if (state === 'cached') bgColor = 'bg-primary/60';

        // Current block is brighter with highlight
        if (isCurrent) {
          bgColor = 'bg-primary';
        }

        // Seek target gets yellow highlight
        if (isSeekTarget) {
          bgColor = 'bg-yellow-400';
        }

        return (
          <div
            key={idx}
            className={`h-full transition-colors duration-150 hover:brightness-110 ${bgColor}`}
            style={{
              flex: '1 1 0',
              minWidth: 0,
              borderRight: idx < numBlocks - 1 ? '1px solid rgba(0,0,0,0.1)' : 'none',
              boxShadow: isSeekTarget ? 'inset 0 0 0 2px oklch(0.75 0.15 85)' : 'none',
            }}
            title={`Block ${idx + 1}: ${state}`}
          />
        );
      })}
    </div>
  );
}

interface ProgressBarValues {
  estimated_ms: number | undefined;
  numberOfBlocks: number | undefined;
  currentBlock: number | undefined;
  setCurrentBlock: (value: number) => void;
  onBlockHover?: (idx: number | null, isDragging: boolean) => void;
  audioProgress: number;
  blockStates: BlockState[];
}

interface Props {
  isPlaying: boolean;
  isBuffering: boolean;
  isSynthesizing: boolean;
  isReconnecting?: boolean;
  connectionError?: string | null;
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

const SoundControl = ({
  isPlaying,
  isBuffering,
  isSynthesizing,
  isReconnecting,
  connectionError,
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
}: Props) => {
  const { estimated_ms, numberOfBlocks, currentBlock, setCurrentBlock, onBlockHover, audioProgress, blockStates } = progressBarValues;
  const [progressDisplay, setProgressDisplay] = useState("0:00");
  const [durationDisplay, setDurationDisplay] = useState("0:00");
  const [isHoveringSpinner, setIsHoveringSpinner] = useState(false);
  const [isMobileExpanded, setIsMobileExpanded] = useState(false);

  // Get sidebar state for responsive positioning
  const { state: sidebarState, isMobile } = useSidebar();

  const numBlocks = numberOfBlocks ?? 0;

  // Long-press repeat with acceleration for skip buttons
  const skipBackProps = useRepeatOnHold(onSkipBack, (currentBlock ?? 0) <= 0 && !isPlaying);
  const skipForwardProps = useRepeatOnHold(onSkipForward, (currentBlock ?? 0) >= numBlocks - 1);

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
          onClick={isBuffering || isSynthesizing ? onCancelSynthesis : isPlaying ? onPause : onPlay}
          onMouseEnter={() => (isBuffering || isSynthesizing) && setIsHoveringSpinner(true)}
          onMouseLeave={() => setIsHoveringSpinner(false)}
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
      <div className="flex items-center gap-4 max-w-2xl mx-auto">
        <span className="text-sm text-muted-foreground w-12 text-right tabular-nums">
          {progressDisplay}
        </span>
        {blockStates.length > SMOOTH_THRESHOLD ? (
          <SmoothProgressBar
            blockStates={blockStates}
            currentBlock={currentBlock ?? 0}
            onBlockClick={setCurrentBlock}
            onBlockHover={onBlockHover}
          />
        ) : (
          <BlockyProgressBar
            blockStates={blockStates}
            currentBlock={currentBlock ?? 0}
            onBlockClick={setCurrentBlock}
            onBlockHover={onBlockHover}
          />
        )}
        <span className="text-sm text-muted-foreground w-12 tabular-nums">
          {durationDisplay}
        </span>
      </div>

      {/* Mobile: block info + expand toggle (always visible) */}
      {isMobile && (
        <div className="flex items-center justify-between mt-2 max-w-2xl mx-auto">
          <span className="text-xs text-muted-foreground">
            Block {blockNum} of {numBlocks}
          </span>
          {(isReconnecting || connectionError) && (
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

      {/* Mobile expanded: voice, speed, volume in vertical layout */}
      {isMobile && isMobileExpanded && (
        <div className="mt-3 pt-3 border-t border-border/50 max-w-2xl mx-auto space-y-3">
          <VoicePicker value={voiceSelection} onChange={onVoiceChange} />
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">Speed</span>
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground font-mono tabular-nums w-10">
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
          </div>
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">Volume</span>
            <div className="flex items-center gap-2">
              <Volume2 className="h-4 w-4 text-muted-foreground" />
              <Slider
                value={[volume]}
                max={100}
                step={1}
                onValueChange={(values) => onVolumeChange(values[0])}
                className="w-32"
              />
            </div>
          </div>
          <div className="flex justify-end">
            <SettingsDialog />
          </div>
        </div>
      )}

      {/* Desktop: horizontal layout with all controls */}
      {!isMobile && (
        <div className="flex items-center justify-between mt-2 max-w-2xl mx-auto">
          <div className="flex items-center gap-3">
            <VoicePicker value={voiceSelection} onChange={onVoiceChange} />
            <span className="text-xs text-muted-foreground">
              Block {blockNum} of {numBlocks}
            </span>
            {(isReconnecting || connectionError) && (
              <span className={`flex items-center gap-1 text-xs ${connectionError ? 'text-destructive' : 'text-yellow-600'}`}>
                <WifiOff className="h-3 w-3" />
                {connectionError || 'Reconnecting...'}
              </span>
            )}
          </div>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground font-mono tabular-nums w-10">
                {playbackSpeed.toFixed(1)}x
              </span>
              <Slider
                value={[playbackSpeed]}
                min={0.5}
                max={3}
                step={0.1}
                onValueChange={(values) => onSpeedChange(values[0])}
                className="w-24"
              />
            </div>
            <div className="flex items-center gap-2">
              <Volume2 className="h-4 w-4 text-muted-foreground" />
              <Slider
                value={[volume]}
                max={100}
                step={1}
                onValueChange={(values) => onVolumeChange(values[0])}
                className="w-24"
              />
            </div>
            <SettingsDialog />
          </div>
        </div>
      )}
    </div>
  );
};

export { SoundControl };

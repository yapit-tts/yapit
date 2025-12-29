import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Play, Pause, Volume2, SkipBack, SkipForward, Loader2, Square, WifiOff, ChevronUp } from "lucide-react";
import { useEffect, useState, useRef, useCallback } from "react";
import { VoicePicker } from "@/components/voicePicker";
import { SettingsDialog } from "@/components/settingsDialog";
import { type VoiceSelection } from "@/lib/voiceSelection";
import { useSidebar } from "@/components/ui/sidebar";

type BlockState = 'pending' | 'synthesizing' | 'cached';

// Switch to smooth gradient visualization for documents with many blocks
const SMOOTH_THRESHOLD = 200;

interface ProgressBarProps {
  blockStates: BlockState[];
  currentBlock: number;
  onBlockClick: (idx: number) => void;
}

// Smooth gradient visualization for large documents
function SmoothProgressBar({ blockStates, currentBlock, onBlockClick }: ProgressBarProps) {
  const barRef = useRef<HTMLDivElement>(null);
  const numBlocks = blockStates.length;

  const getBlockFromX = useCallback((clientX: number) => {
    if (!barRef.current) return 0;
    const rect = barRef.current.getBoundingClientRect();
    const x = clientX - rect.left;
    const pct = Math.max(0, Math.min(1, x / rect.width));
    return Math.min(numBlocks - 1, Math.floor(pct * numBlocks));
  }, [numBlocks]);

  const handleClick = (e: React.MouseEvent) => {
    const blockIdx = getBlockFromX(e.clientX);
    onBlockClick(blockIdx);
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
      className="flex-1 h-10 md:h-5 rounded overflow-hidden cursor-pointer relative"
      style={{ background: gradient }}
      onClick={handleClick}
      role="slider"
      aria-valuemin={1}
      aria-valuemax={numBlocks}
      aria-valuenow={currentBlock + 1}
      tabIndex={0}
    >
      {/* Position indicator for current block */}
      <div
        className="absolute top-0 bottom-0 w-0.5 bg-foreground/80 pointer-events-none"
        style={{ left: `${currentPct}%` }}
      />
    </div>
  );
}

// Individual block visualization for smaller documents
function BlockyProgressBar({ blockStates, currentBlock, onBlockClick }: ProgressBarProps) {
  const numBlocks = blockStates.length;

  // Debug: log what we're receiving
  console.log(`[BlockyProgressBar] numBlocks=${numBlocks}, currentBlock=${currentBlock}, states:`,
    blockStates.slice(0, 10).map((s, i) => `${i}:${s}`).join(', '));

  if (numBlocks === 0) {
    console.log('[BlockyProgressBar] No blocks, showing empty bar');
    return <div className="flex-1 h-10 md:h-5 bg-muted rounded" />;
  }

  // Always show individual blocks filling the entire width (like a health bar)
  // Each block is an equal slice of the total width
  return (
    <div className="flex-1 flex items-center h-10 md:h-5 bg-muted/30 rounded overflow-hidden">
      {blockStates.map((state, idx) => {
        const isCurrent = idx === currentBlock;

        // State-based colors
        let bgColor = 'bg-muted/50'; // pending - subtle gray
        if (state === 'synthesizing') bgColor = 'bg-yellow-500/70 animate-pulse';
        else if (state === 'cached') bgColor = 'bg-primary/60';

        // Current block is brighter with highlight
        if (isCurrent) {
          bgColor = 'bg-primary';
        }

        return (
          <button
            key={idx}
            className={`h-full transition-colors duration-150 hover:brightness-110 ${bgColor}`}
            style={{
              flex: '1 1 0',
              minWidth: 0,
              // Tiny gap between blocks (border creates the divider effect)
              borderRight: idx < numBlocks - 1 ? '1px solid rgba(0,0,0,0.1)' : 'none',
            }}
            onClick={() => onBlockClick(idx)}
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
  const { estimated_ms, numberOfBlocks, currentBlock, setCurrentBlock, audioProgress, blockStates } = progressBarValues;
  const [progressDisplay, setProgressDisplay] = useState("0:00");
  const [durationDisplay, setDurationDisplay] = useState("0:00");
  const [isHoveringSpinner, setIsHoveringSpinner] = useState(false);
  const [isMobileExpanded, setIsMobileExpanded] = useState(false);

  // Get sidebar state for responsive positioning
  const { state: sidebarState, isMobile } = useSidebar();

  useEffect(() => {
    setProgressDisplay(msToTime(audioProgress));
  }, [audioProgress]);

  useEffect(() => {
    setDurationDisplay(msToTime(estimated_ms));
  }, [estimated_ms]);

  const numBlocks = numberOfBlocks ?? 0;
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
          onClick={onSkipBack}
          disabled={(currentBlock ?? 0) <= 0 && !isPlaying}
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
          onClick={onSkipForward}
          disabled={(currentBlock ?? 0) >= numBlocks - 1}
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
          />
        ) : (
          <BlockyProgressBar
            blockStates={blockStates}
            currentBlock={currentBlock ?? 0}
            onBlockClick={setCurrentBlock}
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

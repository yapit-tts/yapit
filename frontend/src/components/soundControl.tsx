import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Play, Pause, Volume2, SkipBack, SkipForward, Loader2, Square } from "lucide-react";
import { useEffect, useState } from "react";
import { VoicePicker } from "@/components/voicePicker";
import { type VoiceSelection } from "@/lib/voiceSelection";

interface ProgressBarValues {
  estimated_ms: number | undefined;
  numberOfBlocks: number | undefined;
  currentBlock: number | undefined;
  setCurrentBlock: (value: number) => void;
  audioProgress: number;
}

interface Props {
  isPlaying: boolean;
  isSynthesizing: boolean;
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
  isSynthesizing,
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
  const { estimated_ms, numberOfBlocks, currentBlock, setCurrentBlock, audioProgress } = progressBarValues;
  const [progressDisplay, setProgressDisplay] = useState("0:00");
  const [durationDisplay, setDurationDisplay] = useState("0:00");
  const [isHoveringSpinner, setIsHoveringSpinner] = useState(false);

  useEffect(() => {
    setProgressDisplay(msToTime(audioProgress));
  }, [audioProgress]);

  useEffect(() => {
    setDurationDisplay(msToTime(estimated_ms));
  }, [estimated_ms]);

  const handleSliderChange = (newValue: number[]) => {
    const newBlock = newValue[0];
    if (newBlock !== currentBlock) {
      setCurrentBlock(newBlock);
    }
  };

  const numBlocks = numberOfBlocks ?? 0;
  const blockNum = (currentBlock ?? 0) + 1;

  return (
    <div className="fixed bottom-0 left-64 right-0 bg-background/80 backdrop-blur-lg border-t border-border p-4">
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
          onClick={isSynthesizing ? onCancelSynthesis : isPlaying ? onPause : onPlay}
          onMouseEnter={() => isSynthesizing && setIsHoveringSpinner(true)}
          onMouseLeave={() => setIsHoveringSpinner(false)}
        >
          {isSynthesizing ? (
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

      {/* Progress bar and info */}
      <div className="flex items-center gap-4 max-w-2xl mx-auto">
        <span className="text-sm text-muted-foreground w-12 text-right tabular-nums">
          {progressDisplay}
        </span>
        <Slider
          value={[currentBlock ?? 0]}
          max={Math.max(numBlocks - 1, 0)}
          step={1}
          onValueChange={handleSliderChange}
          className="flex-1"
        />
        <span className="text-sm text-muted-foreground w-12 tabular-nums">
          {durationDisplay}
        </span>
      </div>

      {/* Voice picker, block info, speed, and volume */}
      <div className="flex items-center justify-between mt-2 max-w-2xl mx-auto">
        <div className="flex items-center gap-3">
          <VoicePicker value={voiceSelection} onChange={onVoiceChange} />
          <span className="text-xs text-muted-foreground">
            Block {blockNum} of {numBlocks}
          </span>
        </div>
        <div className="flex items-center gap-4">
          {/* Speed control slider */}
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
          {/* Volume control */}
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
        </div>
      </div>
    </div>
  );
};

export { SoundControl };

import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Slider } from "@/components/ui/slider";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Play, Pause, Volume2, Rewind, FastForward } from "lucide-react";
import { useRef, useState, useEffect } from "react";

interface ProgressBarValues {
	estimated_ms: number | undefined;
	numberOfBlocks: number | undefined;
	currentBlock: number;
};

interface Props {
  isPlaying: boolean;
  onPlay: () => void;
  onPause: () => void;
	style: React.CSSProperties;
	progressBarValues: ProgressBarValues;
};

const SoundControl = ({ isPlaying, onPlay, onPause, style, progressBarValues }: Props) => {
	const estimatedAudioLengthMs = useRef<number>(progressBarValues.estimated_ms ?? 0);
	const [audioProgressBlock, setAudioProgressBlock] = useState<number>(progressBarValues.currentBlock);
	const [estimatedAudioLength, setEstimatedAudioLength] = useState<string>("00:00");
	const [audioProgress, setAudioProgress] = useState<string>("00:00");

	// Calculate estimated audio length
	useEffect(() => {
		setEstimatedAudioLength(msToTime(estimatedAudioLengthMs.current));
	}, []);

	// Start/Pause increasing audio progress
	useEffect(() => {
		
	}, [isPlaying]);

	function msToTime(duration: number | undefined) {
		if (duration == undefined) duration = 0;

		let seconds: number = Math.floor((duration / 1000) % 60),
			minutes: number = Math.floor((duration / (1000 * 60)) % 60),
			hours: number = Math.floor((duration / (1000 * 60 * 60)) % 24);

		let hoursStr: string = (hours < 10) ? "0" + hours : hours.toString(),
		minutesStr: string = (minutes < 10) ? "0" + minutes : minutes.toString(),
		secondsStr:string = (seconds < 10) ? "0" + seconds : seconds.toString();

		return (hours == 0) ? minutesStr + ":" + secondsStr : hoursStr + ":" + minutesStr + ":" + secondsStr;
	}

	return (
		<div className="flex flex-col fixed bottom-0 p-4 border-t-1 border-t-border backdrop-blur-lg space-y-6 justify-center items-center" style={style}>
			<div className="flex flex-row w-full space-x-8 justify-center items-center">
				<Button variant="outline" size="lg"><Rewind /></Button>
				<Button variant="secondary" size="lg" onClick={isPlaying ? onPause : onPlay}>{isPlaying ? <Pause /> : <Play />}</Button>
				<Button variant="outline" size="lg"><FastForward /></Button>
			</div>
			<div className="flex flex-row w-full space-x-6 items-center justify-center">
				<DropdownMenu>
					<DropdownMenuTrigger>Tara</DropdownMenuTrigger>
					<DropdownMenuContent>
						<DropdownMenuLabel>Voice</DropdownMenuLabel>
						<DropdownMenuSeparator />
						<DropdownMenuItem>Tara</DropdownMenuItem>
						<DropdownMenuItem>Leo</DropdownMenuItem>
						<DropdownMenuItem>Cloe</DropdownMenuItem>
					</DropdownMenuContent>
				</DropdownMenu>
				<div className="flex flex-row w-[60%] items-center space-x-2">
					<Slider defaultValue={[0]} max={100} step={100 / 3} value={[progressBarValues.currentBlock]} />
					<p className="text-nowrap">{ audioProgress } / { estimatedAudioLength }</p>
				</div>
				<div className="flex flex-row w-[12%] items-center space-x-2">
					<Volume2 />
					<Slider defaultValue={[33]} max={100} step={1} />
				</div>
				<DropdownMenu>
					<DropdownMenuTrigger>1.0x</DropdownMenuTrigger>
					<DropdownMenuContent>
						<DropdownMenuLabel>Playback Speed</DropdownMenuLabel>
						<DropdownMenuSeparator />
						<DropdownMenuItem>1.0x</DropdownMenuItem>
						<DropdownMenuItem>1.25x</DropdownMenuItem>
						<DropdownMenuItem>1.5x</DropdownMenuItem>
						<DropdownMenuItem>1.75x</DropdownMenuItem>
						<DropdownMenuItem>2.0x</DropdownMenuItem>
					</DropdownMenuContent>
				</DropdownMenu>
			</div>
		</div>
	)
}

export { SoundControl }   

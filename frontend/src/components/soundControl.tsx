import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Slider } from "@/components/ui/slider";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Play, Volume2, Rewind, FastForward } from "lucide-react";

function SoundControl() {
	return (
		<div className="flex flex-col fixed bottom-0 w-full p-4 border-t-2 border-t-black backdrop-blur-lg space-y-6 justify-center items-center">
			<div className="flex flex-row w-full space-x-8 justify-center items-center">
				<Button variant="outline" size="lg"><Rewind /></Button>
				<Button size="lg"><Play /></Button>
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
					<Progress value={25} />
					<p className="text-nowrap">00:15 / 01:00</p>
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

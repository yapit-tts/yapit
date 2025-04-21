import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Slider } from "@/components/ui/slider";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Play, Volume2 } from "lucide-react";

function SoundControl() {
	return (
		<div className="flex flex-row fixed bottom-0 w-full p-4 border-t-2 border-t-black space-x-4 justify-center items-center">
			<Button><Play /></Button>
			<Progress value={25} className="w-[30%]" />
			<p>00:15 / 01:00</p>
			<Volume2 />
			<Slider defaultValue={[33]} max={100} step={1} className="w-[10%]"/>
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
	)
}

export { SoundControl }   

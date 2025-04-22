import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Play } from "lucide-react";

function DocumentUpload() {
	return (
		<div className="flex flex-col w-full items-center space-y-8">
			<div className="flex flex-row w-[50%]">
				<Textarea />
			</div>
			<Button><Play />&nbsp;Start&nbsp;Listening</Button>
		</div>
	)
}

export { DocumentUpload }

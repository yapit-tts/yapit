import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle, } from "@/components/ui/card";


const DocumentCard = ({ inputText }) => {
	return (
		<div className="flex flex-col overflow-y-auto m-[10%] mt-[4%]">
			<p className="mb-[4%] text-4xl font-bold">Lorem Ipsum</p>
			<p>
				{inputText}	
			</p>
		</div>
	)
}

export { DocumentCard }

type Props = {
	inputText: string | undefined;
};

const DocumentCard = ({ inputText }: Props) => {
	return (
		<div className="flex flex-col overflow-y-auto m-[10%] mt-[4%]">
			<p className="mb-[4%] text-4xl font-bold border-b-1 border-b-border">Lorem Ipsum</p>
			<pre className="whitespace-pre-wrap break-words w-full">
				{inputText}	
			</pre>
		</div>
	)
}

export { DocumentCard }

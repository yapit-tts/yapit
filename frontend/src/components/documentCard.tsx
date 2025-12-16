type Props = {
	title: string | undefined;
	content: string;
};

const DocumentCard = ({ title, content }: Props) => {
	return (
		<div className="flex flex-col overflow-y-auto m-[10%] mt-[4%]">
			<p className="mb-[4%] text-4xl font-bold border-b-1 border-b-border">{ title }</p>
			<pre className="whitespace-pre-wrap break-words w-full">
				{ content }
			</pre>
		</div>
	)
}

export { DocumentCard }

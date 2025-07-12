import {Separator} from "@/components/ui/separator";

type Props = {
	title: string | undefined;
};

const PageTitle = ({ title }: Props) => {
	return (
		<div className="flex flex-col overflow-y-auto m-[10%] mt-[4%]">
			<h2 className="text-4xl">
			{ title }
			</h2>
			<Separator />	
		</div>
	)
}

export { PageTitle }

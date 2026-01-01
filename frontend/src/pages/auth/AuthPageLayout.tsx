import { ReactNode } from "react";

interface AuthPageLayoutProps {
	children: ReactNode;
}

export default function AuthPageLayout({ children }: AuthPageLayoutProps) {
	return (
		<div className="min-h-screen bg-background flex flex-col items-center pt-[15vh] px-4">
			<div className="w-full max-w-lg scale-125 origin-top">{children}</div>
		</div>
	);
}

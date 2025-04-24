import { ReactNode } from 'react';
import { Navbar } from "@/components/navbar";

const MainLayout = ({ children }: { children: ReactNode }) => {
	return (
		<div>
			<Navbar />	
			<main>{children}</main>
		</div>
	);
};

export default MainLayout;

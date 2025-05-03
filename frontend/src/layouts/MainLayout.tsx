import { ReactNode } from 'react';
import { Navbar } from "@/components/navbar";
import SidebarLayout from "@/layouts/SidebarLayout";

const MainLayout = ({ children }: { children: ReactNode }) => {
	return (
		<div>
			<Navbar />
			<SidebarLayout><main>{children}</main></SidebarLayout>
		</div>
	)
}

export default MainLayout;

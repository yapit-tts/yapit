import { ReactNode } from 'react';
import SidebarLayout from "@/layouts/SidebarLayout";

const MainLayout = ({ children }: { children: ReactNode }) => {
	return (
		<SidebarLayout>
			<main>{children}</main>
		</SidebarLayout>
	)
}

export default MainLayout;

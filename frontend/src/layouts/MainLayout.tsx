import { ReactNode, useEffect } from 'react';
import { useNavigate } from 'react-router';
import { useUser } from '@stackframe/react';
import SidebarLayout from "@/layouts/SidebarLayout";

const MainLayout = ({ children }: { children: ReactNode }) => {
	const user = useUser();
	const navigate = useNavigate();

	useEffect(() => {
		if (user) {
			const returnTo = localStorage.getItem("returnAfterSignIn");
			if (returnTo) {
				localStorage.removeItem("returnAfterSignIn");
				navigate(returnTo);
			}
		}
	}, [user, navigate]);

	return (
		<SidebarLayout>
			<main>{children}</main>
		</SidebarLayout>
	)
}

export default MainLayout;

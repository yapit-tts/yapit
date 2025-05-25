import { Routes, Route, useLocation } from "react-router";
import MainLayout from "../layouts/MainLayout";
import PlaybackPage from "../pages/PlaybackPage";
import TextInputPage from "@/pages/TextInputPage";
import { stackClientApp } from "@/auth";
import { StackHandler } from "@stackframe/react";
import { FC } from "react";
import { AuthTest } from "@/pages/AuthTest";

const AuthRoutes: FC = () => {
	const location = useLocation();

	return (
		<StackHandler
			app={stackClientApp}
			location={location.pathname.replace("auth", "handler")}
			fullPage
		/>
	);
};

const AppRoutes = () => (
	<Routes>
		<Route path="/auth/*" element={<AuthRoutes />} />
		<Route path="/authtest" element={<AuthTest />} />
		<Route
			path="/input"
			element={
				<MainLayout>
					<TextInputPage />
				</MainLayout>
			}
		/>
		<Route
			path="/playback"
			element={
				<MainLayout>
					<PlaybackPage />
				</MainLayout>
			}
		/>
	</Routes>
);

export default AppRoutes;

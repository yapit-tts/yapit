import { Routes, Route, useLocation } from "react-router";
import MainLayout from "../layouts/MainLayout";
import PlaybackPage from "../pages/PlaybackPage";
import TextInputPage from "@/pages/TextInputPage";
import AdminPanelPage from "@/pages/AdminPanelPage";
import { stackClientApp } from "@/auth";
import { StackHandler } from "@stackframe/react";
import { FC } from "react";
import { AuthTest } from "@/pages/AuthTest";

const AuthRoutes: FC = () => {
	const location = useLocation();

	return (
		<StackHandler app={stackClientApp} location={location.pathname} fullPage />
	);
};

const AppRoutes = () => (
	<Routes>
		<Route path="/handler/*" element={<AuthRoutes />} />
		<Route path="/authtest" element={<AuthTest />} />
		<Route
			path="/"
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
		<Route
			path="/admin"
			element={
				<MainLayout>
					<AdminPanelPage />
				</MainLayout>
			}
		/>
	</Routes>
);

export default AppRoutes;

import { Routes, Route, useLocation } from "react-router";
import MainLayout from "../layouts/MainLayout";
import PlaybackPage from "../pages/PlaybackPage";
import TextInputPage from "@/pages/TextInputPage";
import AdminPanelPage from "@/pages/AdminPanelPage";
import SettingsPage from "@/pages/SettingsPage";
import CheckoutSuccessPage from "@/pages/CheckoutSuccessPage";
import CheckoutCancelPage from "@/pages/CheckoutCancelPage";
import { stackClientApp } from "@/auth";
import { StackHandler } from "@stackframe/react";
import { FC } from "react";

const AuthRoutes: FC = () => {
	const location = useLocation();

	return (
		<StackHandler app={stackClientApp} location={location.pathname} fullPage />
	);
};

const AppRoutes = () => (
	<Routes>
		<Route path="/handler/*" element={<AuthRoutes />} />
		<Route
			path="/"
			element={
				<MainLayout>
					<TextInputPage />
				</MainLayout>
			}
		/>
		<Route
			path="/playback/:documentId"
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
		<Route
			path="/settings"
			element={
				<MainLayout>
					<SettingsPage />
				</MainLayout>
			}
		/>
		<Route
			path="/checkout/success"
			element={
				<MainLayout>
					<CheckoutSuccessPage />
				</MainLayout>
			}
		/>
		<Route
			path="/checkout/cancel"
			element={
				<MainLayout>
					<CheckoutCancelPage />
				</MainLayout>
			}
		/>
	</Routes>
);

export default AppRoutes;

import { Routes, Route, useLocation } from "react-router";
import MainLayout from "../layouts/MainLayout";
import PlaybackPage from "../pages/PlaybackPage";
import TextInputPage from "@/pages/TextInputPage";
import AdminPanelPage from "@/pages/AdminPanelPage";
import SubscriptionPage from "@/pages/SubscriptionPage";
import CheckoutSuccessPage from "@/pages/CheckoutSuccessPage";
import CheckoutCancelPage from "@/pages/CheckoutCancelPage";
import TermsPage from "@/pages/TermsPage";
import PrivacyPage from "@/pages/PrivacyPage";
import NotFoundPage from "@/pages/NotFoundPage";
import SignInPage from "@/pages/auth/SignInPage";
import SignUpPage from "@/pages/auth/SignUpPage";
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
		<Route path="/handler/sign-in" element={<SignInPage />} />
		<Route path="/handler/sign-up" element={<SignUpPage />} />
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
			path="/subscription"
			element={
				<MainLayout>
					<SubscriptionPage />
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
		<Route path="/terms" element={<TermsPage />} />
		<Route path="/privacy" element={<PrivacyPage />} />
		<Route path="*" element={<NotFoundPage />} />
	</Routes>
);

export default AppRoutes;

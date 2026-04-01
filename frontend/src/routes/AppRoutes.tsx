import { lazy, Suspense } from "react";
import { Routes, Route, useLocation } from "react-router";
import { Loader2 } from "lucide-react";
import MainLayout from "../layouts/MainLayout";
import TextInputPage from "@/pages/TextInputPage";
import UrlCatchAllPage from "@/pages/UrlCatchAllPage";
import { authEnabled, stackClientApp } from "@/auth";
import { ChunkErrorBoundary } from "@/components/ChunkErrorBoundary";

const PlaybackPage = lazy(() => import("@/pages/PlaybackPage"));
const SubscriptionPage = lazy(() => import("@/pages/SubscriptionPage"));
const TipsPage = lazy(() => import("@/pages/TipsPage"));
const AccountPage = lazy(() => import("@/pages/AccountPage"));
const AccountSettingsPage = lazy(() => import("@/pages/AccountSettingsPage"));
const AboutPage = lazy(() => import("@/pages/AboutPage"));
const CheckoutSuccessPage = lazy(() => import("@/pages/CheckoutSuccessPage"));
const CheckoutCancelPage = lazy(() => import("@/pages/CheckoutCancelPage"));
const TermsPage = lazy(() => import("@/pages/TermsPage"));
const PrivacyPage = lazy(() => import("@/pages/PrivacyPage"));
const BatchStatusPage = lazy(() => import("@/pages/BatchStatusPage"));
const SignInPage = lazy(() => import("@/pages/auth/SignInPage"));
const SignUpPage = lazy(() => import("@/pages/auth/SignUpPage"));

const LazyStackHandler = lazy(() =>
	import("@stackframe/react").then((m) => ({ default: m.StackHandler })),
);

function Loading() {
	return (
		<div className="flex items-center justify-center min-h-[50vh]">
			<Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
		</div>
	);
}

function Lazy({ children }: { children: React.ReactNode }) {
	return (
		<ChunkErrorBoundary>
			<Suspense fallback={<Loading />}>{children}</Suspense>
		</ChunkErrorBoundary>
	);
}

const AuthRoutes = () => {
	const location = useLocation();

	return (
		<Lazy>
			<LazyStackHandler
				app={stackClientApp!}
				location={location.pathname}
				fullPage
			/>
		</Lazy>
	);
};

const AppRoutes = () => (
	<Routes>
		{authEnabled && (
			<>
				<Route path="/handler/sign-in" element={<Lazy><SignInPage /></Lazy>} />
				<Route path="/handler/sign-up" element={<Lazy><SignUpPage /></Lazy>} />
				<Route path="/handler/*" element={<AuthRoutes />} />
			</>
		)}
		<Route
			path="/"
			element={
				<MainLayout>
					<TextInputPage />
				</MainLayout>
			}
		/>
		<Route
			path="/listen/:documentId"
			element={
				<MainLayout>
					<Lazy><PlaybackPage /></Lazy>
				</MainLayout>
			}
		/>
		<Route
			path="/batch/:contentHash"
			element={
				<MainLayout>
					<Lazy><BatchStatusPage /></Lazy>
				</MainLayout>
			}
		/>
		{authEnabled && (
			<>
				<Route
					path="/subscription"
					element={
						<MainLayout>
							<Lazy><SubscriptionPage /></Lazy>
						</MainLayout>
					}
				/>
				<Route
					path="/account/settings"
					element={
						<MainLayout>
							<Lazy><AccountSettingsPage /></Lazy>
						</MainLayout>
					}
				/>
				<Route
					path="/checkout/success"
					element={
						<MainLayout>
							<Lazy><CheckoutSuccessPage /></Lazy>
						</MainLayout>
					}
				/>
				<Route
					path="/checkout/cancel"
					element={
						<MainLayout>
							<Lazy><CheckoutCancelPage /></Lazy>
						</MainLayout>
					}
				/>
			</>
		)}
		<Route
			path="/tips"
			element={
				<MainLayout>
					<Lazy><TipsPage /></Lazy>
				</MainLayout>
			}
		/>
		<Route
			path="/account"
			element={
				<MainLayout>
					<Lazy><AccountPage /></Lazy>
				</MainLayout>
			}
		/>
		<Route
			path="/about"
			element={
				<MainLayout>
					<Lazy><AboutPage /></Lazy>
				</MainLayout>
			}
		/>
		<Route path="/terms" element={<Lazy><TermsPage /></Lazy>} />
		<Route path="/privacy" element={<Lazy><PrivacyPage /></Lazy>} />
		<Route path="*" element={<UrlCatchAllPage />} />
	</Routes>
);

export default AppRoutes;

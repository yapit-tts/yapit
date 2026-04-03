import { StackProvider, StackTheme } from "@stackframe/react";
import { Component, Suspense, type ErrorInfo, type ReactNode } from "react";
import AppRoutes from "@/routes/AppRoutes";
import { authEnabled, stackClientApp } from "@/auth";
import { ApiProvider } from "@/api";
import { SettingsProvider } from "@/hooks/useSettings";
import { SubscriptionProvider } from "@/hooks/useSubscription";
import { UserPreferencesProvider } from "@/hooks/useUserPreferences";
import { StackAuthBridge, NoAuthBridge } from "@/hooks/useAuthUser";

const stackTheme = {
	light: {
		primary: "#4d8b5c",
	},
	dark: {
		primary: "#4d8b5c",
	},
};

class AuthErrorBoundary extends Component<
	{ children: ReactNode },
	{ failed: boolean }
> {
	state = { failed: false };

	static getDerivedStateFromError() {
		return { failed: true };
	}

	componentDidCatch(error: Error, info: ErrorInfo) {
		console.error("Auth provider failed:", error, info);
	}

	render() {
		if (this.state.failed) {
			return (
				<div style={{ padding: "2rem", fontFamily: "system-ui" }}>
					<h2>Authentication service unavailable</h2>
					<p style={{ color: "#666" }}>
						Stack Auth is not reachable. If you're self-hosting:
					</p>
					<ul style={{ color: "#666", lineHeight: 1.8 }}>
						<li>
							Uncomment the Stack Auth section in{" "}
							<code>.env.selfhost</code> and restart with{" "}
							<code>make self-host-auth</code>
						</li>
						<li>
							Or switch to single-user mode:{" "}
							<code>make self-host</code> (no auth required)
						</li>
					</ul>
				</div>
			);
		}
		return this.props.children;
	}
}

function App() {
	const content = (
		<Suspense fallback={null}>
			<SettingsProvider>
				<ApiProvider>
					<SubscriptionProvider>
						<UserPreferencesProvider>
							<AppRoutes />
						</UserPreferencesProvider>
					</SubscriptionProvider>
				</ApiProvider>
			</SettingsProvider>
		</Suspense>
	);

	if (authEnabled && stackClientApp) {
		return (
			<AuthErrorBoundary>
				<StackProvider app={stackClientApp}>
					<StackTheme theme={stackTheme}>
						<StackAuthBridge>{content}</StackAuthBridge>
					</StackTheme>
				</StackProvider>
			</AuthErrorBoundary>
		);
	}

	return <NoAuthBridge>{content}</NoAuthBridge>;
}

export default App;

import { StackProvider, StackTheme } from "@stackframe/react";
import { Suspense } from "react";
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
			<StackProvider app={stackClientApp}>
				<StackTheme theme={stackTheme}>
					<StackAuthBridge>{content}</StackAuthBridge>
				</StackTheme>
			</StackProvider>
		);
	}

	return <NoAuthBridge>{content}</NoAuthBridge>;
}

export default App;

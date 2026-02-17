import { StackProvider, StackTheme } from "@stackframe/react";
import { Suspense } from "react";
import AppRoutes from "@/routes/AppRoutes";
import { stackClientApp } from "@/auth";
import { ApiProvider } from "@/api";
import { SettingsProvider } from "@/hooks/useSettings";
import { SubscriptionProvider } from "@/hooks/useSubscription";
import { UserPreferencesProvider } from "@/hooks/useUserPreferences";

const stackTheme = {
	light: {
		primary: "#4d8b5c",
	},
	dark: {
		primary: "#4d8b5c",
	},
};

function App() {
	return (
		<StackProvider app={stackClientApp}>
			<StackTheme theme={stackTheme}>
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
			</StackTheme>
		</StackProvider>
	);
}

export default App;

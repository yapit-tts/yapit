import { Suspense } from "react";
import AppRoutes from "@/routes/AppRoutes";
import { ApiProvider } from "@/api";
import { SettingsProvider } from "@/hooks/useSettings";
import { SubscriptionProvider } from "@/hooks/useSubscription";
import { UserPreferencesProvider } from "@/hooks/useUserPreferences";
import { AuthProvider } from "@/hooks/useAuthUser";

function App() {
	return (
		<AuthProvider>
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
		</AuthProvider>
	);
}

export default App;

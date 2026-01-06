import { StackProvider, StackTheme } from "@stackframe/react";
import { Suspense } from "react";
import "./App.css";
import AppRoutes from "@/routes/AppRoutes";
import { stackClientApp } from "@/auth";
import { ApiProvider } from "@/api";
import { SettingsProvider } from "@/hooks/useSettings";
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
							<UserPreferencesProvider>
								<AppRoutes />
							</UserPreferencesProvider>
						</ApiProvider>
					</SettingsProvider>
				</Suspense>
			</StackTheme>
		</StackProvider>
	);
}

export default App;

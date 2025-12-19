import { StackProvider } from "@stackframe/react";
import "./App.css";
import AppRoutes from "@/routes/AppRoutes";
import { stackClientApp } from "@/auth";
import { ApiProvider } from "@/api";
import { SettingsProvider } from "@/hooks/useSettings";

function App() {
	return (
		<StackProvider app={stackClientApp}>
			<SettingsProvider>
				<ApiProvider>
					<AppRoutes />
				</ApiProvider>
			</SettingsProvider>
		</StackProvider>
	);
}

export default App;

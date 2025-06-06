import { StackProvider } from "@stackframe/react";
import "./App.css";
import AppRoutes from "@/routes/AppRoutes";
import { stackClientApp } from "@/auth";
import { ApiProvider } from "@/api";

function App() {
	return (
		<>
			<StackProvider app={stackClientApp}>
				<ApiProvider>
					<AppRoutes />
				</ApiProvider>
			</StackProvider>
		</>
	);
}

export default App;

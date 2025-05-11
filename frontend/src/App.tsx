import { StackProvider } from "@stackframe/react";
import "./App.css";
import AppRoutes from "@/routes/AppRoutes";
import { stackClientApp } from "@/auth";

function App() {
	return (
		<>
			<StackProvider app={stackClientApp}>
				<AppRoutes />
			</StackProvider>
		</>
	);
}

export default App;

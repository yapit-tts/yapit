import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";
import tailwindcss from "@tailwindcss/vite";

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
	const env = loadEnv(
		mode,
		path.join(path.dirname(process.cwd()), "..", ".env"),
		"VITE_",
	);

	console.log(env);
	console.log(path.join(path.dirname(process.cwd()), "..", ".env"));

	return {
		plugins: [react(), tailwindcss()],
		resolve: {
			alias: {
				"@": path.resolve(__dirname, "./src"),
			},
		},
		define: {
			__APP_ENV__: JSON.stringify(env.APP_ENV),
		},
	};
});

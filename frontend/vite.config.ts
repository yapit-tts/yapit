import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";
import tailwindcss from "@tailwindcss/vite";

// https://vite.dev/config/
export default defineConfig(() => {
	return {
		plugins: [
			react({
				babel: {
					plugins: [["babel-plugin-react-compiler"]],
				},
			}),
			tailwindcss(),
		],
		resolve: {
			alias: {
				"@": path.resolve(__dirname, "./src"),
			},
		},
		server: {
			fs: {
				allow: [".", ".."],
			},
			proxy: {
				// Same origin as in prod, so the session cookie reaches the gateway
				"/api": {
					target: "http://localhost:8000",
					rewrite: (path) => path.replace(/^\/api/, ""),
					ws: true,
				},
				"/images": {
					target: "http://localhost:8000",
					changeOrigin: true,
				},
			},
		},
		test: {
			globals: true,
			environment: "jsdom",
			setupFiles: ["./src/test-setup.ts"],
		},
	};
});

import { StackClientApp } from "@stackframe/react";
import { useNavigate } from "react-router";

export const authEnabled = !!import.meta.env.VITE_STACK_AUTH_PROJECT_ID;

export const stackClientApp = authEnabled
	? new StackClientApp({
			baseUrl:
				import.meta.env.VITE_STACK_BASE_URL ?? "http://localhost:8102",
			projectId: import.meta.env.VITE_STACK_AUTH_PROJECT_ID,
			publishableClientKey: import.meta.env.VITE_STACK_AUTH_CLIENT_KEY,
			tokenStore: "cookie",
			redirectMethod: {
				useNavigate,
			},
		})
	: null;

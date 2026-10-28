import axios from "axios";

const baseURL = import.meta.env.VITE_API_BASE_URL;

export interface AuthUser {
	id: string;
	email: string;
	name: string | null;
	identities: { provider: string; email: string | null }[];
}

export interface SessionState {
	auth_enabled: boolean;
	user: AuthUser | null;
}

export async function fetchSession(): Promise<SessionState> {
	const { data } = await axios.get<SessionState>(`${baseURL}/v1/auth/session`);
	return data;
}

export async function signOut(): Promise<void> {
	await axios.post(`${baseURL}/v1/auth/sign-out`);
}

/** The gateway's own words for a failed sign-in request, or a generic line when it gave none. */
export function signInError(err: unknown): string {
	if (axios.isAxiosError(err)) {
		const detail = err.response?.data?.detail;
		if (typeof detail === "string") return detail;
		if (err.response?.status === 422) return "That doesn't look like an email address.";
	}
	return "Something went wrong. Please try again.";
}

export async function emailSignInLink(email: string): Promise<void> {
	await axios.post(`${baseURL}/v1/auth/email/start`, { email });
}

export async function verifySignIn(
	body: { token: string; same_browser_only?: boolean } | { email: string; code: string },
): Promise<void> {
	await axios.post(`${baseURL}/v1/auth/email/verify`, body);
}

/** Whether the gateway refused a link because another browser asked for it, which a click overrides. */
export function isOtherBrowser(err: unknown): boolean {
	return axios.isAxiosError(err) && err.response?.status === 409;
}

import axios from "axios";

const baseURL = import.meta.env.VITE_API_BASE_URL;

export interface AuthUser {
	id: string;
	email: string;
	name: string | null;
	identities: { provider: string; email: string | null }[];
}

export type OAuthProvider = "google" | "github";

export const PROVIDER_NAMES: Record<OAuthProvider, string> = { google: "Google", github: "GitHub" };

export interface SessionState {
	auth_enabled: boolean;
	/** The OAuth providers this server offers; one without a client id is left out. */
	providers: OAuthProvider[];
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

/** Where to send the browser to sign in with (or, signed in, connect) a Google or GitHub account. */
export function oauthStartUrl(provider: OAuthProvider, mode: "sign_in" | "link", returnTo: string): string {
	const params = new URLSearchParams({ mode, return_to: returnTo });
	return `${baseURL}/v1/auth/oauth/${provider}/start?${params}`;
}

/** The words for an `?error=` code the OAuth callback redirects with. */
export function oauthErrorMessage(code: string): string {
	switch (code) {
		case "denied":
			return "Sign-in was cancelled.";
		case "state":
			return "That sign-in took too long or was started in another browser. Please try again.";
		case "email_unverified":
			return "Your Google or GitHub account has no verified email address. Verify it there, or sign in with email.";
		case "identity_taken":
			return "That account already signs in to another Yapit account.";
		case "not_signed_in":
			return "Sign in first, then connect the account.";
		default:
			return "Signing in with Google or GitHub failed. Please try again, or sign in with email.";
	}
}

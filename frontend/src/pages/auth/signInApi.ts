import axios from "axios";

const baseURL = import.meta.env.VITE_API_BASE_URL;

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

export async function verifySignIn(body: { token: string } | { email: string; code: string }): Promise<void> {
	await axios.post(`${baseURL}/v1/auth/email/verify`, body);
}

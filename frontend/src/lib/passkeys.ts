import axios from "axios";
import { authErrorMessage } from "@/lib/authApi";

const baseURL = import.meta.env.VITE_API_BASE_URL;

/*
 * The gateway speaks WebAuthn's JSON form, where every binary field is base64url text;
 * navigator.credentials takes and returns ArrayBuffers. The converters below translate
 * the few fields that differ, in both directions.
 */

type Json = Record<string, unknown>;

interface CeremonyOptions {
	flow: string;
	options: Json;
}

export interface PasskeyInfo {
	id: string;
	label: string;
	created: string;
	last_used: string | null;
}

export function passkeysSupported(): boolean {
	return typeof window !== "undefined" && typeof window.PublicKeyCredential === "function";
}

/** Whether the browser can offer passkeys in the email field's autofill (WebAuthn conditional mediation). */
export async function passkeyAutofillAvailable(): Promise<boolean> {
	if (!passkeysSupported()) return false;
	return (await PublicKeyCredential.isConditionalMediationAvailable?.()) ?? false;
}

/** Add a passkey to the signed-in account: the browser asks for the key, a touch and its PIN. */
export async function addPasskey(label: string): Promise<PasskeyInfo> {
	const { data: started } = await axios.post<CeremonyOptions>(`${baseURL}/v1/auth/passkeys/register/options`);
	const credential = (await navigator.credentials.create({
		publicKey: creationOptions(started.options),
	})) as PublicKeyCredential | null;
	if (!credential) throw new DOMException("No passkey was created.", "NotAllowedError");
	const { data } = await axios.post<PasskeyInfo>(`${baseURL}/v1/auth/passkeys`, {
		flow: started.flow,
		credential: registrationJson(credential),
		label,
	});
	return data;
}

/**
 * Sign in with a passkey the browser holds for this site. With `autofill`, the request waits in the
 * background and the browser offers the passkeys in the email field's suggestions; `signal` ends it.
 */
export async function signInWithPasskey({ autofill = false, signal }: { autofill?: boolean; signal?: AbortSignal } = {}) {
	const { data: started } = await axios.post<CeremonyOptions>(`${baseURL}/v1/auth/passkeys/sign-in/options`);
	const credential = (await navigator.credentials.get({
		publicKey: requestOptions(started.options),
		mediation: autofill ? "conditional" : undefined,
		signal,
	})) as PublicKeyCredential | null;
	if (!credential) throw new DOMException("No passkey was chosen.", "NotAllowedError");
	await axios.post(`${baseURL}/v1/auth/passkeys/sign-in`, {
		flow: started.flow,
		credential: assertionJson(credential),
	});
}

export async function listPasskeys(): Promise<PasskeyInfo[]> {
	const { data } = await axios.get<PasskeyInfo[]>(`${baseURL}/v1/auth/passkeys`);
	return data;
}

export async function renamePasskey(id: string, label: string): Promise<void> {
	await axios.patch(`${baseURL}/v1/auth/passkeys/${id}`, { label });
}

export async function removePasskey(id: string): Promise<void> {
	await axios.delete(`${baseURL}/v1/auth/passkeys/${id}`);
}

/** The words for a failed passkey request, or null when the person cancelled it themselves. */
export function passkeyErrorMessage(err: unknown): string | null {
	if (!(err instanceof DOMException)) return authErrorMessage(err);
	switch (err.name) {
		case "NotAllowedError":
		case "AbortError":
			return null; // cancelled, timed out, or replaced by another request
		case "InvalidStateError":
			return "This passkey is already added to your account.";
		case "SecurityError":
			return "This browser refused passkeys for this site.";
		default:
			return "Your browser could not use the passkey. Please try again.";
	}
}

function fromBase64url(text: string): ArrayBuffer {
	const base64 = text.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(text.length / 4) * 4, "=");
	const binary = atob(base64);
	const bytes = new Uint8Array(binary.length);
	for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
	return bytes.buffer;
}

function toBase64url(buffer: ArrayBuffer): string {
	const bytes = new Uint8Array(buffer);
	let binary = "";
	for (const byte of bytes) binary += String.fromCharCode(byte);
	return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function descriptors(list: unknown): PublicKeyCredentialDescriptor[] | undefined {
	if (!Array.isArray(list)) return undefined;
	return list.map((d: Json) => ({ ...d, id: fromBase64url(d.id as string) }) as PublicKeyCredentialDescriptor);
}

function creationOptions(options: Json): PublicKeyCredentialCreationOptions {
	const user = options.user as Json;
	return {
		...(options as unknown as PublicKeyCredentialCreationOptions),
		challenge: fromBase64url(options.challenge as string),
		user: { ...(user as unknown as PublicKeyCredentialUserEntity), id: fromBase64url(user.id as string) },
		excludeCredentials: descriptors(options.excludeCredentials),
	};
}

function requestOptions(options: Json): PublicKeyCredentialRequestOptions {
	return {
		...(options as unknown as PublicKeyCredentialRequestOptions),
		challenge: fromBase64url(options.challenge as string),
		allowCredentials: descriptors(options.allowCredentials),
	};
}

function registrationJson(credential: PublicKeyCredential): Json {
	const response = credential.response as AuthenticatorAttestationResponse;
	return {
		id: credential.id,
		rawId: toBase64url(credential.rawId),
		type: credential.type,
		response: {
			clientDataJSON: toBase64url(response.clientDataJSON),
			attestationObject: toBase64url(response.attestationObject),
			transports: response.getTransports?.() ?? [],
		},
		clientExtensionResults: credential.getClientExtensionResults(),
		authenticatorAttachment: credential.authenticatorAttachment ?? undefined,
	};
}

function assertionJson(credential: PublicKeyCredential): Json {
	const response = credential.response as AuthenticatorAssertionResponse;
	return {
		id: credential.id,
		rawId: toBase64url(credential.rawId),
		type: credential.type,
		response: {
			clientDataJSON: toBase64url(response.clientDataJSON),
			authenticatorData: toBase64url(response.authenticatorData),
			signature: toBase64url(response.signature),
			userHandle: response.userHandle ? toBase64url(response.userHandle) : undefined,
		},
		clientExtensionResults: credential.getClientExtensionResults(),
		authenticatorAttachment: credential.authenticatorAttachment ?? undefined,
	};
}

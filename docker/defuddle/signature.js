/**
 * Web Bot Auth request signatures (RFC 9421 HTTP Message Signatures, as Cloudflare's
 * Web Bot Auth page profiles them): an Ed25519 signature over the request's
 * authority and its Signature-Agent header, which names where the public key is served.
 */

import { createHash, createPrivateKey, createPublicKey, randomBytes, sign } from "node:crypto";

const LIFETIME_S = 60;

/**
 * A function from a request URL to the three signature headers, or null when no key is set.
 * `privateKey` is a base64 PKCS#8 DER Ed25519 key; `appUrl` the https origin serving
 * /.well-known/http-message-signatures-directory.
 */
export function requestSigner(privateKey, appUrl) {
	if (!privateKey) return null;
	const agentOrigin = new URL(appUrl).origin;
	// Cloudflare fails a Signature-Agent that is not https.
	if (!agentOrigin.startsWith("https://")) throw new Error("APP_URL must be https to sign requests");
	const key = createPrivateKey({ key: Buffer.from(privateKey, "base64"), format: "der", type: "pkcs8" });
	if (key.asymmetricKeyType !== "ed25519") throw new Error("WEB_BOT_AUTH_PRIVATE_KEY is not an Ed25519 key");
	const keyid = jwkThumbprint(createPublicKey(key).export({ format: "jwk" }));
	const signatureAgent = `"${agentOrigin}"`;

	return (url, now = Date.now(), nonce = randomBytes(64).toString("base64")) => {
		const created = Math.floor(now / 1000);
		const params =
			`("@authority" "signature-agent");created=${created};keyid="${keyid}";alg="ed25519"` +
			`;expires=${created + LIFETIME_S};nonce="${nonce}";tag="web-bot-auth"`;
		const base =
			`"@authority": ${new URL(url).host}\n` +
			`"signature-agent": ${signatureAgent}\n` +
			`"@signature-params": ${params}`;
		return {
			"Signature-Agent": signatureAgent,
			"Signature-Input": `sig1=${params}`,
			Signature: `sig1=:${sign(null, Buffer.from(base), key).toString("base64")}:`,
		};
	};
}

/** RFC 7638 thumbprint of an OKP public JWK, as RFC 8037 appendix A.3 computes it. */
export function jwkThumbprint({ crv, kty, x }) {
	return createHash("sha256").update(JSON.stringify({ crv, kty, x })).digest("base64url");
}

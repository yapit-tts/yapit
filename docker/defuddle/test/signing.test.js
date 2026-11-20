import { after, test } from "node:test";
import assert from "node:assert/strict";
import { createPrivateKey } from "node:crypto";
import { verify } from "web-bot-auth";
import { verifierFromJWK } from "web-bot-auth/crypto";
import { ARTICLE, SHELL, html, redirect, stubWeb, text } from "./stub-web.js";

// The Ed25519 test key of RFC 9421, appendix B.1.4. Its thumbprint is the keyid Cloudflare's
// research server lists for it at /.well-known/http-message-signatures-directory.
const RFC_9421_KEY = {
	kty: "OKP",
	crv: "Ed25519",
	d: "n4Ni-HpISpVObnQMW0wOhCKROaIKqKtW_2ZYb2p9KcU",
	x: "JrQLj5P_89iXES9-vFgrIy29clF9CC_oPPsw3c5D0bs",
};
const RFC_9421_KEYID = "poqkLGiymh_W0uP6PZFw-dvez3QJT5SolqXBCW38r0U";

const web = await stubWeb((req, res) => {
	if (req.url === "/robots.txt") return text(res, "User-agent: *\nAllow: /\n");
	if (req.url === "/moved") return redirect(res, "http://elsewhere.test/page");
	// Chromium names image types in Accept; the plain fetch does not.
	if (req.url === "/app") return html(res, req.headers.accept?.includes("image/") ? ARTICLE : SHELL);
	html(res, ARTICLE);
});
const service = await web.start({
	WEB_BOT_AUTH_PRIVATE_KEY: createPrivateKey({ key: RFC_9421_KEY, format: "jwk" }).export({ format: "der", type: "pkcs8" }).toString("base64"),
	APP_URL: "https://yapit.example",
});
after(() => service.close());

const extract = (url) => service.post("/extract", { url, timeout_ms: 20_000 });

/** Cloudflare's verifier, given the request as the site received it. */
async function verifyAsCloudflare(seen) {
	const verifier = await verifierFromJWK({ kty: "OKP", crv: "Ed25519", x: RFC_9421_KEY.x });
	const request = new Request(`http://${seen.host}${seen.path}`, {
		headers: {
			Signature: seen.headers["signature"],
			"Signature-Input": seen.headers["signature-input"],
			"Signature-Agent": seen.headers["signature-agent"],
		},
	});
	return verify(request, {
		resolver: (candidate) => {
			assert.equal(candidate.keyid, verifier.keyid);
			return verifier;
		},
	});
}

async function assertSignedForItsAuthority(seen) {
	assert.ok(seen, "the site saw the request");
	assert.equal(seen.headers["signature-agent"], '"https://yapit.example"');
	assert.match(seen.headers["signature-input"], /^sig1=\("@authority" "signature-agent"\);/);
	const verified = await verifyAsCloudflare(seen);
	assert.equal(verified.keyid, RFC_9421_KEYID);
	assert.equal(verified.tag, "web-bot-auth");
	assert.equal(verified.signatureAgent.uri, "https://yapit.example");
	assert.ok(verified.expires > new Date(), "not expired on arrival");
}

test("the plain fetch's page request carries a signature Cloudflare's verifier accepts", async () => {
	assert.equal((await extract("http://signed.test/post")).status, 200);
	await assertSignedForItsAuthority(web.requests.find((r) => r.host === "signed.test" && r.path === "/post"));
});

test("robots.txt is requested signed too", async () => {
	await assertSignedForItsAuthority(web.requests.find((r) => r.host === "signed.test" && r.path === "/robots.txt"));
});

test("each redirect hop is signed for its own authority", async () => {
	assert.equal((await extract("http://signed.test/moved")).status, 200);
	await assertSignedForItsAuthority(web.requests.find((r) => r.host === "signed.test" && r.path === "/moved"));
	await assertSignedForItsAuthority(web.requests.find((r) => r.host === "elsewhere.test" && r.path === "/page"));
});

test("Chromium's document request carries a signature Cloudflare's verifier accepts", async () => {
	const response = await extract("http://signed.test/app");
	assert.equal(response.body.extraction_method, "playwright");
	const browserRequest = web.requests.find((r) => r.path === "/app" && r.headers.accept.includes("image/"));
	await assertSignedForItsAuthority(browserRequest);
	assert.equal(browserRequest.headers["user-agent"], "Mozilla/5.0 (compatible; Yapit/1.0; +https://yapit.md/bot)");
});

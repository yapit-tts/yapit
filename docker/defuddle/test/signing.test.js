// The signature itself is the gateway's, held to Cloudflare's outputs in tests/yapit/gateway/test_web_bot_auth.py.
// Here: every request the extraction service sends carries the headers the signer gave for that request's authority.
import { after, test } from "node:test";
import assert from "node:assert/strict";
import { ARTICLE, SHELL, html, redirect, signedFor, stubWeb, text } from "./stub-web.js";

const web = await stubWeb(
	(req, res) => {
		if (req.url === "/robots.txt") return text(res, "User-agent: *\nAllow: /\n");
		if (req.url === "/moved") return redirect(res, "http://elsewhere.test/page");
		// Chromium names image types in Accept; the plain fetch does not.
		const browser = req.headers.accept?.includes("image/");
		if (req.url === "/app") return html(res, browser ? ARTICLE : SHELL);
		if (req.url === "/app-moved") return browser ? redirect(res, "http://elsewhere.test/app") : html(res, SHELL);
		html(res, ARTICLE);
	},
	{ signs: true },
);
const service = await web.start();
after(() => service.close());

const extract = (url) => service.post("/extract", { url, timeout_ms: 20_000 });
const fromBrowser = (r) => r.headers.accept.includes("image/");

function assertSignedFor(seen, authority) {
	assert.ok(seen, `the site saw the request to ${authority}`);
	const expected = signedFor(authority);
	assert.equal(seen.headers["signature"], expected.Signature);
	assert.equal(seen.headers["signature-input"], expected["Signature-Input"]);
	assert.equal(seen.headers["signature-agent"], expected["Signature-Agent"]);
}

test("the plain fetch's page request and robots.txt carry the signature for their authority", async () => {
	assert.equal((await extract("http://signed.test/post")).status, 200);
	assertSignedFor(web.requests.find((r) => r.host === "signed.test" && r.path === "/post"), "signed.test");
	assertSignedFor(web.requests.find((r) => r.host === "signed.test" && r.path === "/robots.txt"), "signed.test");
});

test("each redirect hop of the plain fetch is signed for its own authority", async () => {
	assert.equal((await extract("http://moving.test/moved")).status, 200);
	assertSignedFor(web.requests.find((r) => r.host === "moving.test" && r.path === "/moved"), "moving.test");
	assertSignedFor(web.requests.find((r) => r.host === "elsewhere.test" && r.path === "/page"), "elsewhere.test");
});

test("Chromium's document requests, across a redirect to another host, are signed for their own authority", async () => {
	const response = await extract("http://chromium-moves.test/app-moved");
	assert.equal(response.body.extraction_method, "playwright");
	const browserRequest = (host, path) => web.requests.find((r) => r.host === host && r.path === path && fromBrowser(r));
	assertSignedFor(browserRequest("chromium-moves.test", "/app-moved"), "chromium-moves.test");
	assertSignedFor(browserRequest("elsewhere.test", "/app"), "elsewhere.test");
	assert.equal(browserRequest("elsewhere.test", "/app").headers["user-agent"], "Mozilla/5.0 (compatible; Yapit/1.0; +https://yapit.md/bot)");
});

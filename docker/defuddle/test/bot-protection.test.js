import { after, test } from "node:test";
import assert from "node:assert/strict";
import { SHELL, html, stubWeb, text } from "./stub-web.js";

// What Cloudflare serves a request from a hosting provider's address on a protected site.
const challenge = (res) =>
	html(res, "<!doctype html><title>Just a moment...</title><p>Checking your browser before accessing the site.</p>", 403, {
		"cf-mitigated": "challenge",
	});

const web = await stubWeb((req, res) => {
	if (req.url === "/robots.txt") return text(res, "", 404);
	if (req.url === "/challenged") return challenge(res);
	if (req.url === "/forbidden") return html(res, "<p>Forbidden</p>", 403);
	// Chromium names image types in Accept; the plain fetch does not.
	if (req.url === "/app") return req.headers.accept?.includes("image/") ? challenge(res) : html(res, SHELL);
	html(res, "<p>ok</p>");
});
const service = await web.start();
after(() => service.close());

const extract = (url) => service.post("/extract", { url, timeout_ms: 20_000 });

test("a Cloudflare challenge is reported as the site's bot protection blocking yapit", async () => {
	const response = await extract("http://protected.test/challenged");
	assert.equal(response.status, 422);
	assert.match(response.body.error, /bot protection/);
	assert.equal(web.requestsFor("/challenged").length, 1, "the cascade stops at the first challenge");
});

test("a challenge Chromium meets is reported the same way", async () => {
	const response = await extract("http://protected.test/app");
	assert.equal(response.status, 422);
	assert.match(response.body.error, /bot protection/);
});

test("a 403 without the challenge header is no bot-protection block", async () => {
	const response = await extract("http://protected.test/forbidden");
	assert.equal(response.status, 200);
	assert.equal(response.body.markdown, "");
});

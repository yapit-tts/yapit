import { after, test } from "node:test";
import assert from "node:assert/strict";
import { ARTICLE, SHELL, html, redirect, stubWeb, text } from "./stub-web.js";

// Each case is its own host, with its own robots.txt.
const ROBOTS = {
	"allows-yapit.test": "User-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nAllow: /\n",
	"refuses-yapit.test": "User-agent: *\nAllow: /\n\nUser-agent: Yapit\nDisallow: /\n",
	"refuses-all.test": "User-agent: *\nDisallow: /\n",
	"spa.test": "User-agent: *\nDisallow: /private\n",
};

const FRAMED = `<!doctype html><title>Framed</title><iframe src="/frame-a"></iframe><iframe src="/frame-b"></iframe>`;

const web = await stubWeb((req, res) => {
	const host = req.headers.host.split(":")[0];
	if (req.url === "/robots.txt") {
		if (host === "missing.test") return text(res, "not found", 404);
		if (host === "down.test") return text(res, "unavailable", 503);
		if (host === "busy.test") return text(res, "slow down", 429);
		return text(res, ROBOTS[host] ?? "");
	}
	if (req.url === "/old") return redirect(res, "/private");
	// Chromium names image types in Accept; the plain fetch does not.
	const browser = req.headers.accept?.includes("image/");
	if (req.url === "/app-to-private") return browser ? redirect(res, "/private") : html(res, SHELL);
	if (req.url === "/app-to-page") return browser ? redirect(res, "/page") : html(res, SHELL);
	if (req.url === "/framed-moved") return browser ? redirect(res, "/framed") : html(res, SHELL);
	if (req.url === "/framed") return html(res, browser ? FRAMED : SHELL);
	html(res, ARTICLE);
});
const service = await web.start();
after(() => service.close());

const extract = (url) => service.post("/extract", { url, timeout_ms: 20_000 });

function assertRefusedByRobots(response) {
	assert.equal(response.status, 422);
	assert.match(response.body.error, /robots\.txt/);
}

test("a page robots.txt allows yapit is extracted, though it refuses another bot", async () => {
	const response = await extract("http://allows-yapit.test/page");
	assert.equal(response.status, 200);
	assert.match(response.body.markdown, /Ringstrasse/);
});

test("a page robots.txt disallows for yapit is refused without being requested", async () => {
	assertRefusedByRobots(await extract("http://refuses-yapit.test/article"));
	assert.equal(web.requestsFor("/article").length, 0);
});

test("a site whose robots.txt disallows everyone is refused", async () => {
	assertRefusedByRobots(await extract("http://refuses-all.test/page"));
	assert.equal(web.requests.filter((r) => r.host === "refuses-all.test" && r.path !== "/robots.txt").length, 0);
});

test("a site with no robots.txt is fetched", async () => {
	const response = await extract("http://missing.test/page");
	assert.equal(response.status, 200);
	assert.match(response.body.markdown, /Prater/);
});

test("a site whose robots.txt cannot be read is refused", async () => {
	assertRefusedByRobots(await extract("http://down.test/page"));
	assert.equal(web.requests.filter((r) => r.host === "down.test" && r.path === "/page").length, 0);
});

test("a site whose robots.txt answers 429 is refused", async () => {
	assertRefusedByRobots(await extract("http://busy.test/page"));
	assert.equal(web.requests.filter((r) => r.host === "busy.test" && r.path === "/page").length, 0);
});

test("a site that does not answer at all reads as a link that cannot be reached, not as robots.txt", async () => {
	const response = await extract("https://gone.test/page");
	assert.equal(response.status, 422);
	assert.match(response.body.error, /Unable to reach URL/);
	assert.equal(web.requests.filter((r) => r.host === "gone.test" && r.path === "/page").length, 0);
});

test("a redirect into a disallowed path is refused before the request to it", async () => {
	assertRefusedByRobots(await extract("http://spa.test/old"));
	assert.equal(web.requestsFor("/private").length, 0);
});

test("Chromium checks every redirect hop of the page against robots.txt", async () => {
	assertRefusedByRobots(await extract("http://spa.test/app-to-private"));
	assert.equal(web.requestsFor("/private").length, 0);
});

test("one extraction reads a site's robots.txt once, across its redirect and Chromium's frames", async () => {
	await extract("http://framed.test/framed-moved");
	const seen = web.requests.filter((r) => r.host === "framed.test");
	for (const path of ["/framed", "/frame-a", "/frame-b"]) assert.ok(seen.some((r) => r.path === path), `Chromium requested ${path}`);
	assert.equal(seen.filter((r) => r.path === "/robots.txt").length, 1);
});

test("the gateway's robots check answers for a URL without fetching it", async () => {
	assert.equal((await service.post("/robots", { url: "http://spa.test/fine" })).status, 200);
	assertRefusedByRobots(await service.post("/robots", { url: "http://spa.test/private/x" }));
	assert.equal(web.requestsFor("/fine").length, 0);
});

test("without a key, every request goes out unsigned", async () => {
	const response = await extract("http://unsigned.test/app-to-page");
	assert.equal(response.body.extraction_method, "playwright");
	assert.match(response.body.markdown, /Ringstrasse/, "Chromium followed the redirect to the page");
	const seen = web.requests.filter((r) => r.host === "unsigned.test");
	for (const r of seen) assert.equal(r.headers["signature"] ?? r.headers["signature-input"] ?? r.headers["signature-agent"], undefined);
});

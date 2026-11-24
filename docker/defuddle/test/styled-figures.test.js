// A page whose static extraction holds an inline SVG is drawn in Chromium, so the SVG keeps the look its stylesheet gives it.
import { after, test } from "node:test";
import assert from "node:assert/strict";
import { html, stubWeb, text } from "./stub-web.js";

const PROSE = `<p>We walked from the Ringstrasse to the Prater and back again, stopping at every bakery on the way.</p>
<p>The coffee was strong, the cake was stronger, and the city was quiet in the early morning light.</p>`;

const CHART = `<div class="chart"><svg viewBox="0 0 400 200" role="img" aria-label="Bakeries per street">
<path class="trend" d="M0,200 C100,0 300,0 400,200"></path>
<circle class="dot" cx="200" cy="50" r="9"></circle>
<text class="label" x="10" y="190">Ring</text></svg></div>`;

const STYLES = `.chart svg { stroke-width: 1px; }
.trend { stroke: rgb(20, 40, 60); stroke-width: 2; stroke-dasharray: 6 5; fill: none; }
.dot { fill: rgb(30, 160, 90); }
.label { font-size: 18px; fill: rgb(90, 90, 90); }`;

const page = (body) =>
	`<!doctype html><html><head><title>A walk in Vienna</title><link rel="stylesheet" href="/style.css"></head><body><article><h1>A walk in Vienna</h1>${body}</article></body></html>`;

const web = await stubWeb((req, res) => {
	if (req.url === "/robots.txt") return text(res, "User-agent: *\nAllow: /\n");
	if (req.url === "/style.css") {
		res.writeHead(200, { "Content-Type": "text/css" });
		return res.end(STYLES);
	}
	const browser = req.headers.accept?.includes("image/");
	if (req.url === "/chart") return html(res, page(PROSE + CHART));
	// In the browser the article loses its text, as a page can whose script rewrites it.
	if (req.url === "/chart-emptied") return html(res, page(browser ? CHART : PROSE + CHART));
	if (req.url === "/canvas")
		return html(
			res,
			page(`${PROSE}<canvas width="200" height="100" aria-label="A green block"></canvas>
<script>document.querySelector("canvas").getContext("2d").fillRect(20, 20, 100, 50);</script>${CHART}`),
		);
	html(res, page(PROSE));
});
const service = await web.start();
after(() => service.close());

const extract = (url) => service.post("/extract", { url, timeout_ms: 20_000 });

test("an inline SVG keeps the stroke, dashes, colours and font size its stylesheet gives it", async () => {
	const { body } = await extract("http://site.test/chart");
	assert.equal(body.extraction_method, "playwright-styled");
	const svg = body.markdown.match(/<svg[\s\S]*<\/svg>/)?.[0];
	assert.ok(svg, body.markdown);
	assert.match(svg, /stroke:\s*rgb\(20, 40, 60\)/);
	assert.match(svg, /stroke-dasharray:\s*6px,? 5px/);
	assert.match(svg, /fill:\s*rgb\(30, 160, 90\)/);
	assert.match(svg, /font-size:\s*18px/);
	assert.match(body.markdown, /bakery on the way/);
});

test("a page without an inline SVG stays on the static path", async () => {
	const { body } = await extract("http://site.test/prose");
	assert.equal(body.extraction_method, "static");
});

test("a styled extraction that loses the static one's text gives way to it", async () => {
	const { body } = await extract("http://site.test/chart-emptied");
	assert.equal(body.extraction_method, "static");
	assert.match(body.markdown, /bakery on the way/);
});

test("a drawn canvas on a styled page becomes an image of what it shows", async () => {
	const { body } = await extract("http://site.test/canvas");
	assert.equal(body.extraction_method, "playwright-styled");
	assert.match(body.markdown, /!\[A green block\]\(data:image\/png;base64,/);
});

/**
 * Defuddle extraction service.
 *
 * Cascade: static fetch + linkedom → bot UA retry → Playwright browser fallback.
 * Static extraction handles the vast majority of content sites. Playwright is
 * reserved for JS-rendered SPAs where the HTML is an empty shell.
 */

import http from "node:http";
import { readFileSync } from "node:fs";
import { ProxyAgent, fetch as proxyFetch } from "undici";
import { Defuddle } from "defuddle/node";
import { chromium } from "playwright";

const PROXY_URL = process.env.PROXY_URL;
if (!PROXY_URL) throw new Error("PROXY_URL is required (e.g. http://smokescreen:4750)");

const PORT = 8001;
const MAX_CONCURRENT_BROWSER = 50;
const STATIC_FETCH_TIMEOUT_MS = 5_000;
const MAX_PAGE_SIZE = 20 * 1024 * 1024;
const DEFAULT_UA = "Mozilla/5.0 (compatible; Yapit/1.0; +https://yapit.md)";
const BOT_UA = DEFAULT_UA + " bot";
const BOT_UA_DOMAINS = ["github.com"];

const proxyAgent = new ProxyAgent(PROXY_URL);
const bundle = readFileSync("defuddle_bundle.js", "utf-8");

class CapacityError extends Error {
	constructor() {
		super("Service at capacity");
	}
}

let browser = null;
let browserLaunchPromise = null;
let browserSlots = MAX_CONCURRENT_BROWSER;

// --- Static extraction (fetch + linkedom + defuddle) ---

async function fetchPage(url, userAgent, timeoutMs) {
	const fetchTimeout = Math.min(timeoutMs, STATIC_FETCH_TIMEOUT_MS);
	const controller = new AbortController();
	const timer = setTimeout(() => controller.abort(), fetchTimeout);

	try {
		const response = await proxyFetch(url, {
			headers: {
				"User-Agent": userAgent,
				Accept: "text/html,application/xhtml+xml",
			},
			redirect: "follow",
			signal: controller.signal,
			dispatcher: proxyAgent,
		});

		if (!response.ok) throw new Error(`HTTP ${response.status}`);

		const contentType = response.headers.get("content-type") || "";
		if (
			!contentType.includes("text/html") &&
			!contentType.includes("application/xhtml+xml")
		) {
			throw new Error(`Not HTML (${contentType})`);
		}

		const buffer = await response.arrayBuffer();
		if (buffer.byteLength > MAX_PAGE_SIZE) throw new Error("Page too large");

		return new TextDecoder().decode(buffer);
	} catch (err) {
		if (err.name === "AbortError")
			throw new Error(`Timed out after ${fetchTimeout / 1000}s`);
		throw err;
	} finally {
		clearTimeout(timer);
	}
}

async function extractStatic(url, userAgent, timeoutMs) {
	const html = await fetchPage(url, userAgent, timeoutMs);
	const result = await Defuddle(html, url, { markdown: true });
	return {
		markdown: result.content || "",
		title: result.title || null,
		wordCount: result.wordCount || 0,
	};
}

// --- Playwright extraction (browser rendering + defuddle bundle) ---

async function getBrowser() {
	if (browser?.isConnected()) return browser;
	if (browserLaunchPromise) return browserLaunchPromise;

	browserLaunchPromise = chromium
		.launch({ headless: true, args: ["--disable-dev-shm-usage"] })
		.then((b) => {
			browser = b;
			browserLaunchPromise = null;
			console.log("Chromium started");
			return b;
		})
		.catch((e) => {
			browserLaunchPromise = null;
			throw e;
		});
	return browserLaunchPromise;
}

async function extractPlaywright(url, timeoutMs) {
	const b = await getBrowser();
	const context = await b.newContext({ proxy: { server: PROXY_URL } });
	await context.addInitScript(bundle);
	const page = await context.newPage();

	try {
		const resp = await page.goto(url, {
			waitUntil: "domcontentloaded",
			timeout: timeoutMs,
		});
		if (resp && resp.status() >= 400) {
			console.log(`Playwright got HTTP ${resp.status()} for ${url}`);
			return { markdown: "", title: null };
		}

		return await page.evaluate(async (u) => {
			const d = new Defuddle(document, { url: u, markdown: true });
			const r = await d.parseAsync();
			return { markdown: r.content || "", title: r.title || null };
		}, url);
	} finally {
		await page.close();
		await context.close();
	}
}

// --- Cascade: static → bot UA → Playwright ---

function getInitialUA(url) {
	try {
		const hostname = new URL(url).hostname;
		if (BOT_UA_DOMAINS.some((d) => hostname === d || hostname.endsWith("." + d)))
			return BOT_UA;
	} catch {}
	return DEFAULT_UA;
}

async function extract(url, timeoutMs) {
	const t0 = performance.now();
	const remaining = () => Math.max(0, timeoutMs - (performance.now() - t0));

	const initialUA = getInitialUA(url);
	try {
		const result = await extractStatic(url, initialUA, remaining());
		if (result.wordCount > 0) {
			const method = initialUA === BOT_UA ? "static-bot" : "static";
			log(method, url, t0, result);
			return { markdown: result.markdown, title: result.title, extraction_method: method };
		}
	} catch (e) {
		console.log(`Static failed for ${url}: ${e.message}`);
	}

	if (initialUA !== BOT_UA && remaining() > 1000) {
		try {
			const result = await extractStatic(url, BOT_UA, remaining());
			if (result.wordCount > 0) {
				log("static-bot", url, t0, result);
				return { markdown: result.markdown, title: result.title, extraction_method: "static-bot" };
			}
		} catch (e) {
			console.log(`Static-bot failed for ${url}: ${e.message}`);
		}
	}

	if (browserSlots <= 0) {
		console.warn(`Playwright at capacity (${MAX_CONCURRENT_BROWSER}), rejecting ${url}`);
		throw new CapacityError();
	}

	browserSlots--;
	try {
		const result = await extractPlaywright(url, remaining());
		log("playwright", url, t0, result);
		return { ...result, extraction_method: "playwright" };
	} catch (e) {
		console.error(`Playwright failed for ${url}: ${e.message}`);
		return { markdown: "", title: null, extraction_method: "playwright-error" };
	} finally {
		browserSlots++;
	}
}

function log(method, url, t0, result) {
	const ms = Math.round(performance.now() - t0);
	console.log(`${method}: ${url} ${ms}ms (${result.markdown.length} chars)`);
}

// --- HTTP server ---

async function handleRequest(req, res) {
	if (req.method === "GET" && req.url === "/health") {
		try {
			const b = await getBrowser();
			if (!b.isConnected()) throw new Error("disconnected");
			res.writeHead(200, { "Content-Type": "application/json" });
			res.end('{"status":"ok"}');
		} catch (e) {
			res.writeHead(503, { "Content-Type": "application/json" });
			res.end(JSON.stringify({ status: "error", detail: e.message }));
		}
		return;
	}

	if (req.method === "POST" && req.url === "/extract") {
		let body = "";
		for await (const chunk of req) body += chunk;

		let parsed;
		try {
			parsed = JSON.parse(body);
		} catch {
			res.writeHead(400, { "Content-Type": "application/json" });
			res.end('{"error":"invalid JSON"}');
			return;
		}

		const { url, html, timeout_ms = 30_000 } = parsed;
		if (!url && !html) {
			res.writeHead(400, { "Content-Type": "application/json" });
			res.end('{"error":"url or html required"}');
			return;
		}

		try {
			let result;
			if (html) {
				const t0 = performance.now();
				const r = await Defuddle(html, url || "", { markdown: true });
				const ms = Math.round(performance.now() - t0);
				result = { markdown: r.content || "", title: r.title || null, extraction_method: "html-direct" };
				console.log(`html-direct: ${url || "(uploaded)"} ${ms}ms (${result.markdown.length} chars)`);
			} else {
				result = await extract(url, timeout_ms);
			}
			res.writeHead(200, { "Content-Type": "application/json" });
			res.end(JSON.stringify(result));
		} catch (e) {
			if (e instanceof CapacityError) {
				res.writeHead(503, { "Content-Type": "application/json" });
				res.end('{"error":"Service at capacity, try again shortly"}');
			} else {
				console.error(`Unhandled error for ${url}: ${e.message}`);
				res.writeHead(500, { "Content-Type": "application/json" });
				res.end(JSON.stringify({ error: e.message }));
			}
		}
		return;
	}

	res.writeHead(404);
	res.end();
}

const server = http.createServer(handleRequest);

(async () => {
	await getBrowser();
	server.listen(PORT, () => console.log(`Defuddle service ready on :${PORT}`));
})();

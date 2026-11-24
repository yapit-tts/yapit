/**
 * Defuddle extraction service.
 *
 * Cascade: static fetch + linkedom → bot UA retry → Playwright browser fallback.
 * Static extraction handles the vast majority of content sites. Playwright is
 * reserved for JS-rendered SPAs where the HTML is an empty shell, and for pages whose
 * static extraction holds an inline SVG: only a browser sees the stylesheet that styles it.
 * A Refusal (robots.txt, a site's bot protection) ends the cascade: no other path may fetch the page either.
 */

import http from "node:http";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { Defuddle } from "defuddle/node";
import { chromium } from "playwright";
import { inlineSvgStyles, snapshotCanvases } from "./svg-styles.js";
import { MAX_REDIRECTS, USER_AGENT, Refusal, assertNotChallenged, createFetcher, readCapped } from "./fetcher.js";

const PROXY_URL = process.env.PROXY_URL;
if (!PROXY_URL) throw new Error("PROXY_URL is required (e.g. http://smokescreen:4750)");

const SIGNER_URL = process.env.SIGNER_URL;
if (!SIGNER_URL) throw new Error("SIGNER_URL is required (e.g. http://gateway:8002/sign)");

const PORT = 8001;
const MAX_CONCURRENT_BROWSER = 50;
const STATIC_FETCH_TIMEOUT_MS = 5_000;
const MAX_PAGE_SIZE = 20 * 1024 * 1024;
const BOT_UA = USER_AGENT + " bot";
const BOT_UA_DOMAINS = ["github.com"];
const LOAD_WAIT_MS = 5_000;
// The share of the static extraction's words the styled one has to keep to replace it.
const STYLED_MIN_WORD_SHARE = 0.9;

const fetcher = createFetcher(PROXY_URL, SIGNER_URL);
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

async function fetchPage(call, url, userAgent, timeoutMs) {
	const fetchTimeout = Math.min(timeoutMs, STATIC_FETCH_TIMEOUT_MS);
	const controller = new AbortController();
	const timer = setTimeout(() => controller.abort(), fetchTimeout);

	try {
		const { response } = await call.send(url, {
			userAgent,
			accept: "text/html,application/xhtml+xml",
			signal: controller.signal,
		});

		assertNotChallenged(response.headers.get("cf-mitigated"));
		if (!response.ok) throw new Error(`HTTP ${response.status}`);

		const contentType = response.headers.get("content-type") || "";
		if (
			!contentType.includes("text/html") &&
			!contentType.includes("application/xhtml+xml")
		) {
			throw new Error(`Not HTML (${contentType})`);
		}

		return new TextDecoder().decode(await readCapped(response.body, MAX_PAGE_SIZE));
	} catch (err) {
		if (err.name === "AbortError")
			throw new Error(`Timed out after ${fetchTimeout / 1000}s`);
		throw err;
	} finally {
		clearTimeout(timer);
	}
}

async function extractStatic(call, url, userAgent, timeoutMs) {
	const html = await fetchPage(call, url, userAgent, timeoutMs);
	const result = await Defuddle(html, url, { markdown: true });
	return {
		markdown: result.content || "",
		title: result.title || null,
		wordCount: result.wordCount || 0,
	};
}

function hasInlineSvg(markdown) {
	return /<svg[\s>]/i.test(markdown);
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

async function extractPlaywright(call, url, timeoutMs) {
	const b = await getBrowser();
	// Reduced motion: pages that honour it draw their figures in their final state.
	const context = await b.newContext({ proxy: { server: PROXY_URL }, userAgent: USER_AGENT, reducedMotion: "reduce" });
	await context.addInitScript(bundle);

	// Chromium follows a redirect without asking the route again, so a navigation is fetched
	// here hop by hop: a redirect of the top document is aborted and navigated to anew,
	// which brings its next hop back through this check.
	let refusal = null;
	let redirect = null;
	await context.route("**", async (route) => {
		const request = route.request();
		if (!request.isNavigationRequest()) return route.continue();
		const isTopDocument = request.frame().parentFrame() === null;
		try {
			await call.assertAllowed(request.url());
		} catch (err) {
			if (isTopDocument) refusal = err;
			return route.abort("blockedbyclient");
		}
		const response = await route.fetch({
			headers: { ...request.headers(), ...(await fetcher.signatureHeaders(request.url())) },
			maxRedirects: 0,
		});
		const location = response.headers().location;
		if (response.status() >= 300 && response.status() < 400 && location) {
			if (isTopDocument) redirect = new URL(location, request.url()).href;
			return route.abort("aborted");
		}
		return route.fulfill({ response });
	});
	const page = await context.newPage();

	try {
		let target = url;
		let resp = null;
		for (let hop = 0; ; hop++) {
			refusal = redirect = null;
			resp = await page
				.goto(target, { waitUntil: "domcontentloaded", timeout: timeoutMs })
				.catch((e) => {
					if (refusal || redirect) return null;
					throw e;
				});
			if (refusal) throw refusal;
			if (!redirect) break;
			if (hop === MAX_REDIRECTS) throw new Error("Too many redirects");
			target = redirect;
		}
		if (resp) assertNotChallenged(resp.headers()["cf-mitigated"]);
		if (resp && resp.status() >= 400) {
			console.log(`Playwright got HTTP ${resp.status()} for ${url}`);
			return { markdown: "", title: null, wordCount: 0 };
		}

		await page.waitForLoadState("load", { timeout: Math.min(LOAD_WAIT_MS, timeoutMs) }).catch(() => {});
		await page.evaluate(snapshotCanvases);
		await page.evaluate(inlineSvgStyles);
		return await page.evaluate(async (u) => {
			const d = new Defuddle(document, { url: u, markdown: true });
			const r = await d.parseAsync();
			return { markdown: r.content || "", title: r.title || null, wordCount: r.wordCount || 0 };
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
	return USER_AGENT;
}

async function extract(url, timeoutMs) {
	const t0 = performance.now();
	const remaining = () => Math.max(0, timeoutMs - (performance.now() - t0));
	const call = fetcher.forCall();

	const initialUA = getInitialUA(url);
	try {
		const result = await extractStatic(call, url, initialUA, remaining());
		if (result.wordCount > 0) {
			const method = initialUA === BOT_UA ? "static-bot" : "static";
			if (hasInlineSvg(result.markdown)) {
				const styled = await extractStyled(call, url, result, remaining());
				if (styled) {
					log("playwright-styled", url, t0, styled);
					return { markdown: styled.markdown, title: styled.title, extraction_method: "playwright-styled" };
				}
			}
			log(method, url, t0, result);
			return { markdown: result.markdown, title: result.title, extraction_method: method };
		}
	} catch (e) {
		if (e instanceof Refusal) throw e;
		console.log(`Static failed for ${url}: ${e.message}`);
	}

	if (initialUA !== BOT_UA && remaining() > 1000) {
		try {
			const result = await extractStatic(call, url, BOT_UA, remaining());
			if (result.wordCount > 0) {
				log("static-bot", url, t0, result);
				return { markdown: result.markdown, title: result.title, extraction_method: "static-bot" };
			}
		} catch (e) {
			if (e instanceof Refusal) throw e;
			console.log(`Static-bot failed for ${url}: ${e.message}`);
		}
	}

	if (browserSlots <= 0) {
		console.warn(`Playwright at capacity (${MAX_CONCURRENT_BROWSER}), rejecting ${url}`);
		throw new CapacityError();
	}

	browserSlots--;
	try {
		const result = await extractPlaywright(call, url, remaining());
		log("playwright", url, t0, result);
		return { ...result, extraction_method: "playwright" };
	} catch (e) {
		if (e instanceof Refusal) throw e;
		console.error(`Playwright failed for ${url}: ${e.message}`);
		return { markdown: "", title: null, extraction_method: "playwright-error" };
	} finally {
		browserSlots++;
	}
}

/** The page as a browser draws it, where that keeps the static extraction's text; else null. */
async function extractStyled(call, url, staticResult, timeoutMs) {
	if (browserSlots <= 0 || timeoutMs < 1000) return null;
	browserSlots--;
	try {
		const result = await extractPlaywright(call, url, timeoutMs);
		return result.wordCount >= staticResult.wordCount * STYLED_MIN_WORD_SHARE ? result : null;
	} catch (e) {
		if (e instanceof Refusal) throw e;
		console.log(`Styled extraction failed for ${url}: ${e.message}`);
		return null;
	} finally {
		browserSlots++;
	}
}

function log(method, url, t0, result) {
	const ms = Math.round(performance.now() - t0);
	console.log(`${method}: ${url} ${ms}ms (${result.markdown.length} chars)`);
}

// --- HTTP server ---

function respond(res, status, body) {
	res.writeHead(status, { "Content-Type": "application/json" });
	res.end(JSON.stringify(body));
}

async function readJson(req, res) {
	let body = "";
	for await (const chunk of req) body += chunk;
	try {
		return JSON.parse(body);
	} catch {
		respond(res, 400, { error: "invalid JSON" });
		return null;
	}
}

async function handleRequest(req, res) {
	if (req.method === "GET" && req.url === "/health") {
		try {
			const b = await getBrowser();
			if (!b.isConnected()) throw new Error("disconnected");
			respond(res, 200, { status: "ok" });
		} catch (e) {
			respond(res, 503, { status: "error", detail: e.message });
		}
		return;
	}

	// For the gateway's own download: answers 200 where robots.txt lets yapit fetch the URL, 422 with the reason where not.
	if (req.method === "POST" && req.url === "/robots") {
		const parsed = await readJson(req, res);
		if (!parsed) return;
		try {
			await fetcher.forCall().assertAllowed(parsed.url);
			respond(res, 200, {});
		} catch (e) {
			if (e instanceof Refusal) respond(res, 422, { error: e.message });
			else respond(res, 400, { error: e.message });
		}
		return;
	}

	if (req.method === "POST" && req.url === "/extract") {
		const parsed = await readJson(req, res);
		if (!parsed) return;

		const { url, html, timeout_ms = 30_000 } = parsed;
		if (!url && !html) {
			respond(res, 400, { error: "url or html required" });
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
			respond(res, 200, result);
		} catch (e) {
			if (e instanceof CapacityError) {
				respond(res, 503, { error: "Service at capacity, try again shortly" });
			} else if (e instanceof Refusal) {
				console.log(`Refused ${url}: ${e.message}`);
				respond(res, 422, { error: e.message });
			} else {
				console.error(`Unhandled error for ${url}: ${e.message}`);
				respond(res, 500, { error: e.message });
			}
		}
		return;
	}

	res.writeHead(404);
	res.end();
}

export const server = http.createServer(handleRequest);

export async function closeBrowser() {
	await browser?.close();
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
	await getBrowser();
	server.listen(PORT, () => console.log(`Defuddle service ready on :${PORT}`));
}

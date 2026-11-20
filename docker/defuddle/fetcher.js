/**
 * How yapit's fetcher reaches a site: through the egress proxy, under one user agent,
 * and only where the site's robots.txt allows it, checked on every redirect hop.
 */

import { ProxyAgent, fetch as proxyFetch } from "undici";
import robotsParser from "robots-parser";

export const USER_AGENT = "Mozilla/5.0 (compatible; Yapit/1.0; +https://yapit.md/bot)";
const ROBOTS_PRODUCT_TOKEN = "Yapit";
const MAX_REDIRECTS = 10;
const ROBOTS_MAX_REDIRECTS = 5;
const ROBOTS_TIMEOUT_MS = 5_000;
// RFC 9309 asks a crawler to parse at least 500 KiB of a robots.txt and to keep it no longer than a day.
const ROBOTS_MAX_BYTES = 512 * 1024;
const ROBOTS_TTL_MS = 60 * 60 * 1000;
const ROBOTS_CACHE_ORIGINS = 10_000;

const ROBOTS_DISALLOWED = "This site's robots.txt does not allow yapit to fetch this page";
const ROBOTS_UNREACHABLE = "This site's robots.txt could not be read, and yapit fetches nothing from a site until it can";

/** A page yapit will not fetch, or a site that refused yapit: its message is for the reader. */
export class Refusal extends Error {}

export function createFetcher(proxyUrl) {
	const dispatcher = new ProxyAgent(proxyUrl);
	const robotsCache = new Map();

	/** One request, redirects followed by hand so every hop is checked. Resolves to the final response. */
	async function send(url, { userAgent = USER_AGENT, accept, signal, maxRedirects = MAX_REDIRECTS, checkRobots = true }) {
		for (let hop = 0; ; hop++) {
			if (checkRobots) await assertAllowed(url);
			const response = await proxyFetch(url, {
				headers: { "User-Agent": userAgent, Accept: accept },
				redirect: "manual",
				signal,
				dispatcher,
			});
			const location = response.headers.get("location");
			if (response.status < 300 || response.status >= 400 || !location) return { response, url };
			await response.body?.cancel();
			if (hop === maxRedirects) throw new Error("Too many redirects");
			url = new URL(location, url).href;
		}
	}

	/** Throws a Refusal when robots.txt keeps yapit from `url`. */
	async function assertAllowed(url) {
		const origin = new URL(url).origin;
		let entry = robotsCache.get(origin);
		if (!entry || entry.expires < Date.now()) {
			if (robotsCache.size >= ROBOTS_CACHE_ORIGINS) robotsCache.delete(robotsCache.keys().next().value);
			entry = { expires: Date.now() + ROBOTS_TTL_MS, rules: readRobots(origin) };
			robotsCache.set(origin, entry);
		}
		const rules = await entry.rules;
		if (rules === null) {
			// Not kept: the next page from this site asks again rather than staying refused for an hour.
			if (robotsCache.get(origin) === entry) robotsCache.delete(origin);
			throw new Refusal(ROBOTS_UNREACHABLE);
		}
		if (rules.isAllowed(url, ROBOTS_PRODUCT_TOKEN) === false) throw new Refusal(ROBOTS_DISALLOWED);
	}

	/**
	 * The site's rules (RFC 9309, 2.3.1): a robots.txt answering 4xx allows everything,
	 * one that cannot be reached, answers 5xx or 429, disallows everything (null).
	 */
	async function readRobots(origin) {
		const robotsUrl = `${origin}/robots.txt`;
		try {
			const { response } = await send(robotsUrl, {
				accept: "text/plain",
				signal: AbortSignal.timeout(ROBOTS_TIMEOUT_MS),
				maxRedirects: ROBOTS_MAX_REDIRECTS,
				checkRobots: false,
			});
			if (response.ok) {
				const text = new TextDecoder().decode(await readCapped(response.body, ROBOTS_MAX_BYTES, { truncate: true }));
				return robotsParser(robotsUrl, text);
			}
			await response.body?.cancel();
			if (response.status >= 400 && response.status < 500 && response.status !== 429) return robotsParser(robotsUrl, "");
		} catch (err) {
			console.log(`robots.txt unreachable for ${origin}: ${err.message}`);
		}
		return null;
	}

	return { send, assertAllowed };
}

// fetch decompresses transparently, so a few KB of gzip can expand to gigabytes:
// the cap has to apply to decoded bytes as they arrive, not to the finished body.
export async function readCapped(body, maxBytes, { truncate = false } = {}) {
	const chunks = [];
	let size = 0;
	for await (const chunk of body) {
		size += chunk.byteLength;
		if (size > maxBytes) {
			if (!truncate) throw new Error("Page too large");
			chunks.push(chunk.subarray(0, chunk.byteLength - (size - maxBytes)));
			break;
		}
		chunks.push(chunk);
	}
	return Buffer.concat(chunks);
}

/**
 * How yapit's fetcher reaches a site: through the egress proxy, under one user agent,
 * signed by the gateway where it holds a key, and only where the site's robots.txt allows it,
 * checked on every redirect hop.
 */

import { ProxyAgent, fetch as proxyFetch } from "undici";
import robotsParser from "robots-parser";

export const USER_AGENT = "Mozilla/5.0 (compatible; Yapit/1.0; +https://yapit.md/bot)";
const ROBOTS_PRODUCT_TOKEN = "Yapit";
export const MAX_REDIRECTS = 10;
const ROBOTS_TIMEOUT_MS = 5_000;
const ROBOTS_MAX_BYTES = 512 * 1024;

const ROBOTS_DISALLOWED = "This site's robots.txt does not allow yapit to fetch this page";
const ROBOTS_UNREACHABLE = "This site's robots.txt could not be read, and yapit fetches nothing from a site until it can";
const SITE_UNREACHABLE = "Unable to reach URL - check it's correct and accessible";

const CHALLENGED = "This site's bot protection (Cloudflare) blocked yapit from reading the page";

/** A page yapit will not fetch, or a site that refused yapit: its message is for the reader. */
export class Refusal extends Error {}

/** Cloudflare answers a request it challenges with `cf-mitigated: challenge` in place of the page. */
export function assertNotChallenged(cfMitigated) {
	if (cfMitigated === "challenge") throw new Refusal(CHALLENGED);
}

/** `signerUrl` is the gateway's signer, which answers each request's signature headers, none without a key. */
export function createFetcher(proxyUrl, signerUrl) {
	const dispatcher = new ProxyAgent(proxyUrl);

	async function signatureHeaders(url) {
		const response = await fetch(signerUrl, {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ authority: new URL(url).host }),
		});
		if (!response.ok) throw new Error(`Signer answered HTTP ${response.status}`);
		return response.json();
	}

	/** One request, redirects followed by hand so every hop is checked. Resolves to the final response. */
	async function send(url, { userAgent = USER_AGENT, accept, signal, checkRobots = true }) {
		for (let hop = 0; ; hop++) {
			if (checkRobots) await assertAllowed(url);
			const response = await proxyFetch(url, {
				headers: { "User-Agent": userAgent, Accept: accept, ...(await signatureHeaders(url)) },
				redirect: "manual",
				signal,
				dispatcher,
			});
			const location = response.headers.get("location");
			if (response.status < 300 || response.status >= 400 || !location) return { response, url };
			await response.body?.cancel();
			if (hop === MAX_REDIRECTS) throw new Error("Too many redirects");
			url = new URL(location, url).href;
		}
	}

	/** Throws a Refusal when robots.txt keeps yapit from `url`. */
	async function assertAllowed(url) {
		const rules = await readRobots(new URL(url).origin);
		if (rules.isAllowed(url, ROBOTS_PRODUCT_TOKEN) === false) throw new Refusal(ROBOTS_DISALLOWED);
	}

	/**
	 * The site's rules (RFC 9309, 2.3.1): a robots.txt answering 4xx allows everything; one that
	 * answers 5xx or 429, or not in time, disallows everything, as a Refusal.
	 */
	async function readRobots(origin) {
		const robotsUrl = `${origin}/robots.txt`;
		let response;
		try {
			({ response } = await send(robotsUrl, { accept: "text/plain", signal: AbortSignal.timeout(ROBOTS_TIMEOUT_MS), checkRobots: false }));
			if (response.ok) return robotsParser(robotsUrl, new TextDecoder().decode(await readCapped(response.body, ROBOTS_MAX_BYTES)));
		} catch (err) {
			console.log(`robots.txt unreachable for ${origin}: ${err.message}`);
			// fetch fails with a TypeError when no answer came at all (no such host, a refused connection,
			// the proxy refusing the host): a link nobody can fetch, not a robots.txt that is down.
			throw new Refusal(err instanceof TypeError ? SITE_UNREACHABLE : ROBOTS_UNREACHABLE);
		}
		await response.body?.cancel();
		if (response.status >= 400 && response.status < 500 && response.status !== 429) return robotsParser(robotsUrl, "");
		throw new Refusal(ROBOTS_UNREACHABLE);
	}

	return { send, assertAllowed, signatureHeaders };
}

// fetch decompresses transparently, so a few KB of gzip can expand to gigabytes:
// the cap has to apply to decoded bytes as they arrive, not to the finished body.
export async function readCapped(body, maxBytes) {
	const chunks = [];
	let size = 0;
	for await (const chunk of body) {
		size += chunk.byteLength;
		if (size > maxBytes) throw new Error("Page too large");
		chunks.push(chunk);
	}
	return Buffer.concat(chunks);
}

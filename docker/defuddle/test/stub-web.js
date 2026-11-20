/**
 * A stand-in for the web and for smokescreen: every host the service asks the proxy for
 * is answered by one handler, which sees the host in the request's Host header, except
 * gone.test, which the proxy cannot reach.
 * `start()` then imports the service against that proxy and serves it on a free port.
 */

import http from "node:http";
import net from "node:net";

export async function stubWeb(handler) {
	const requests = [];
	const site = http.createServer((req, res) => {
		requests.push({ host: req.headers.host, path: req.url, headers: req.headers });
		handler(req, res);
	});
	await listen(site);

	const proxy = http.createServer((req, res) => {
		// A plain-http request comes to the proxy in absolute form, from undici and Chromium alike.
		const target = new URL(req.url);
		const upstream = http.request(
			{ host: "127.0.0.1", port: site.address().port, path: target.pathname + target.search, method: req.method, headers: req.headers },
			(r) => {
				res.writeHead(r.statusCode, r.headers);
				r.pipe(res);
			},
		);
		req.pipe(upstream);
	});
	proxy.on("connect", (req, socket, head) => {
		// What smokescreen answers for a host it cannot resolve or reach.
		if (req.url.startsWith("gone.test:")) return socket.end("HTTP/1.1 502 Bad Gateway\r\n\r\n");
		const upstream = net.connect(site.address().port, "127.0.0.1", () => {
			socket.write("HTTP/1.1 200 Connection Established\r\n\r\n");
			upstream.write(head);
			upstream.pipe(socket);
			socket.pipe(upstream);
		});
		upstream.on("error", () => socket.destroy());
		socket.on("error", () => upstream.destroy());
	});
	await listen(proxy);

	return {
		requests,
		/** Requests the site saw for `path` on any host. */
		requestsFor: (path) => requests.filter((r) => r.path === path),
		proxyUrl: `http://127.0.0.1:${proxy.address().port}`,
		async start(env = {}) {
			Object.assign(process.env, { PROXY_URL: this.proxyUrl }, env);
			const service = await import("../app.js");
			await listen(service.server);
			const base = `http://127.0.0.1:${service.server.address().port}`;
			return {
				post: async (path, body) => {
					const r = await fetch(base + path, { method: "POST", body: JSON.stringify(body) });
					return { status: r.status, body: await r.json() };
				},
				close: async () => {
					await service.closeBrowser();
					service.server.close();
					site.closeAllConnections();
					site.close();
					proxy.closeAllConnections();
					proxy.close();
				},
			};
		},
	};
}

export function html(res, body, status = 200, headers = {}) {
	res.writeHead(status, { "Content-Type": "text/html; charset=utf-8", ...headers });
	res.end(body);
}

export function text(res, body, status = 200) {
	res.writeHead(status, { "Content-Type": "text/plain" });
	res.end(body);
}

export function redirect(res, location) {
	res.writeHead(302, { Location: location });
	res.end();
}

export const ARTICLE = `<!doctype html><html><head><title>A walk in Vienna</title></head><body><article>
<h1>A walk in Vienna</h1>
<p>We walked from the Ringstrasse to the Prater and back again, stopping at every bakery on the way.</p>
<p>The coffee was strong, the cake was stronger, and the city was quiet in the early morning light.</p>
</article></body></html>`;

/** An app shell: no text until a script runs, so the cascade reaches Chromium. */
export const SHELL = `<!doctype html><html><head><title>App</title></head><body><div id="root"></div></body></html>`;

function listen(server) {
	return new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
}

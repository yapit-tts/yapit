/**
 * Full-path check of request signing against a verifier that is not ours: Cloudflare Research's
 * server answers "You successfully authenticated as owning the test public key" to a request
 * signed with the RFC 9421 test key. Needs the internet: `make test-extraction-live`.
 */

import assert from "node:assert/strict";
import { createPrivateKey } from "node:crypto";
import http from "node:http";
import net from "node:net";

const RESEARCH_SERVER = "https://http-message-signatures-example.research.cloudflare.com/";
const VERIFIED = /successfully authenticated as owning the test public key/;
const RFC_9421_KEY = {
	kty: "OKP",
	crv: "Ed25519",
	d: "n4Ni-HpISpVObnQMW0wOhCKROaIKqKtW_2ZYb2p9KcU",
	x: "JrQLj5P_89iXES9-vFgrIy29clF9CC_oPPsw3c5D0bs",
};

// A forward proxy to the real internet, standing in for smokescreen.
const proxy = http.createServer((req, res) => res.writeHead(405).end());
proxy.on("connect", (req, socket, head) => {
	const [host, port] = req.url.split(":");
	const upstream = net.connect(Number(port), host, () => {
		socket.write("HTTP/1.1 200 Connection Established\r\n\r\n");
		upstream.write(head);
		upstream.pipe(socket);
		socket.pipe(upstream);
	});
	upstream.on("error", () => socket.destroy());
	socket.on("error", () => upstream.destroy());
});
await new Promise((resolve) => proxy.listen(0, "127.0.0.1", resolve));

Object.assign(process.env, {
	PROXY_URL: `http://127.0.0.1:${proxy.address().port}`,
	WEB_BOT_AUTH_PRIVATE_KEY: createPrivateKey({ key: RFC_9421_KEY, format: "jwk" }).export({ format: "der", type: "pkcs8" }).toString("base64"),
	// The verifier finds the key through Signature-Agent, and the research server's own directory lists the test key.
	APP_URL: RESEARCH_SERVER,
});
// The verdict is in the page's <header>, which extraction drops, so both paths are read raw.
const service = await import("../app.js");
const { createFetcher } = await import("../fetcher.js");
const { requestSigner } = await import("../signature.js");

try {
	const fetcher = createFetcher(process.env.PROXY_URL, requestSigner(process.env.WEB_BOT_AUTH_PRIVATE_KEY, process.env.APP_URL));
	const { response } = await fetcher.send(RESEARCH_SERVER, { accept: "text/html" });
	const plain = await response.text();
	assert.match(plain, VERIFIED, "plain fetch not verified");
	console.log("ok - the plain fetch is verified by Cloudflare Research");

	const rendered = await service.renderPage(RESEARCH_SERVER, 20_000, (page) => page.content());
	assert.match(rendered, VERIFIED, "Chromium's document request not verified");
	console.log("ok - Chromium's document request is verified by Cloudflare Research");
} catch (err) {
	console.error(err);
	process.exitCode = 1;
} finally {
	await service.closeBrowser();
	proxy.close();
	// Chromium's and the proxy's sockets would keep the process alive.
	process.exit();
}

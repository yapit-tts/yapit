# Web Bot Auth: yapit's fetcher as a Cloudflare Verified bot

Sites behind Cloudflare's bot protection challenge requests from hosting providers' addresses, so yapit-prod gets `403` with `cf-mitigated: challenge` where a home connection gets the page. Cloudflare lets a bot through that it has verified. yapit's fetcher is built to qualify as one: an Agent (it visits a page because a reader asked) operated as an Intermediary (many readers drive it).

What the fetcher does, for whoever reads it from outside, is on the page its user agent names: `frontend/src/pages/BotPage.tsx`, served at https://yapit.md/bot.

## The parts

| Part | Where |
| --- | --- |
| One user agent, `Mozilla/5.0 (compatible; Yapit/1.0; +https://yapit.md/bot)`, for every request | `docker/defuddle/fetcher.js`, `yapit/gateway/document/http.py` |
| `robots.txt`, product token `Yapit`, checked before every page request and redirect hop | `docker/defuddle/fetcher.js`; the gateway asks the extraction service's `POST /robots` |
| Request signatures (RFC 9421, Cloudflare's Web Bot Auth profile) | `docker/defuddle/signature.js` for the extraction service, `yapit/gateway/web_bot_auth.py` for the gateway's download |
| The key directory, `/.well-known/http-message-signatures-directory` | `yapit/gateway/web_bot_auth.py`, routed by `frontend/nginx.conf` |
| A `cf-mitigated: challenge` response reported to the reader as the site's bot protection | `docker/defuddle/fetcher.js`, `yapit/gateway/document/http.py` |

Without a key, everything but the signatures and the directory (404) still runs: a self-hosted instance obeys `robots.txt` and names itself the same way.

## The key

An Ed25519 private key, as base64 PKCS#8 DER on one line:

```bash
openssl genpkey -algorithm ed25519 -outform DER | base64 -w0
```

It lives in `.env.sops` as `PROD_WEB_BOT_AUTH_PRIVATE_KEY` ([[env-config]]), so prod alone signs; `.env.dev` and `.env.selfhost.example` leave `WEB_BOT_AUTH_PRIVATE_KEY` empty. On the VPS it reaches two containers and no image: the gateway reads it from `.env`, and the extraction service gets it through compose interpolation (`docker-compose.prod.yml`), with `APP_URL`, the https origin its `Signature-Agent` names. The gateway does not start without the variable, empty or not, since Settings has no defaults.

Cloudflare registers the keys it finds in the directory. A new key means submitting again (Cloudflare's docs: a key already registered is rotated with them), so changing it is an operation, not a deploy.

The extraction service runs Chromium without a sandbox on pages a reader chooses ([[security]]); a renderer exploit there could read the key.

## Checking it

- `make test-extraction` holds both of the extraction service's paths to Cloudflare's `web-bot-auth` verifier; `tests/yapit/gateway/test_web_bot_auth.py` holds the gateway's signatures byte for byte to Cloudflare's outputs.
- `make test-extraction-live` sends both paths' requests, signed with the RFC 9421 test key, to Cloudflare Research's server, which says whether it verified them.
- After a deploy with the key: `cargo install http-signature-directory && http-signature-directory https://yapit.md` validates the live directory the way Cloudflare's tooling does.

## Applying

The application is submitted in the Cloudflare dashboard, under Application security, BotBase, submission form, after the key is deployed: Cloudflare validates against the live directory. Its status shows under BotBase, Submission history. Cloudflare's docs name the verification method and the validation instructions; the other fields below are drafted from what their Verified bots page asks of a bot, since the form itself is visible only from a logged-in dashboard.

| Field | Draft answer |
| --- | --- |
| Bot name | Yapit |
| Operator | Yapit, https://yapit.md |
| Website / documentation | https://yapit.md/bot |
| Contact | yapit@mwolf.dev |
| Verification method | Request Signature |
| Validation instructions | `https://yapit.md/.well-known/http-message-signatures-directory` |
| User agent and match pattern | `Mozilla/5.0 (compatible; Yapit/1.0; +https://yapit.md/bot)`; contains `Yapit/1.0` (the GitHub fetch appends ` bot`) |
| Behaviour (category) | Agent |
| Label | Intermediary |
| robots.txt | Obeyed for the product token `Yapit`, before every page request and every redirect hop; a robots.txt that cannot be read refuses the whole site |

**Description**

> Yapit (https://yapit.md) is an open-source text-to-speech reader. A reader pastes a link into the web app, sends it through the API, or passes it to the `yapit` command line tool, and yapit fetches that one page so it can read its text aloud to that reader. It fetches only the page asked for and the redirects it leads to; it follows no links and crawls nothing of its own accord. A page that needs JavaScript is rendered once in headless Chromium, which loads that page's own scripts, styles and images under the same user agent and signature. Every request carries the user agent above and a Web Bot Auth signature, and yapit obeys `robots.txt` for the token `Yapit`. When a site's bot protection challenges it, yapit stops and tells the reader that the site blocked it; it never presents itself as a browser or as another bot.

**Traffic**

> Two to four requests to the page per link a reader adds (a download that tells a PDF from a web page, then extraction, which may retry once and then render the page in Chromium), plus the site's robots.txt, kept for up to an hour per site. Requests come from yapit's server; verification is by signature, not by address.

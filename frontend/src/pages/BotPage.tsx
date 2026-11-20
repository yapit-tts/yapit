import { useNavigate } from "react-router";
import { Button } from "@/components/ui/button";
import { ArrowLeft } from "lucide-react";

const USER_AGENT = "Mozilla/5.0 (compatible; Yapit/1.0; +https://yapit.md/bot)";

const BotPage = () => {
  const navigate = useNavigate();

  return (
    <div className="container max-w-3xl mx-auto py-12 px-6">
      <Button variant="ghost" className="mb-8" onClick={() => navigate(-1)}>
        <ArrowLeft className="mr-2 h-5 w-5" />
        Back
      </Button>

      <h1 className="text-4xl font-bold mb-8">Yapit's fetcher</h1>

      <div className="prose prose-neutral dark:prose-invert max-w-none space-y-8">
        <section>
          <h2 className="text-2xl font-semibold mb-3">What it is</h2>
          <p>
            Yapit reads documents and web pages aloud. When a reader gives yapit a link, in the web app, through the
            API or with the <code>yapit</code> command line tool, yapit fetches that page so it can turn its text
            into speech for that reader.
          </p>
          <ul className="list-disc pl-6 space-y-1 mt-3">
            <li>It fetches only the page a reader asked for, and the redirects that page leads to.</li>
            <li>It follows no links and crawls nothing on its own.</li>
            <li>
              A page that needs JavaScript to show its text is rendered in a headless browser, which loads the
              page's scripts, styles and images like any browser would.
            </li>
          </ul>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mb-3">How it identifies itself</h2>
          <p>Every request, from the plain fetch and from the headless browser alike, carries this user agent:</p>
          <pre className="mt-3 overflow-x-auto"><code>{USER_AGENT}</code></pre>
          <p className="mt-3">
            Requests from yapit.md are also signed with{" "}
            <a href="https://developers.cloudflare.com/bots/reference/bot-verification/web-bot-auth/" className="text-primary hover:underline">Web Bot Auth</a>{" "}
            (HTTP Message Signatures, RFC 9421). Each carries <code>Signature</code>, <code>Signature-Input</code> and{" "}
            <code>Signature-Agent: "https://yapit.md"</code>, and the public key is listed at{" "}
            <a href="/.well-known/http-message-signatures-directory" className="text-primary hover:underline">
              https://yapit.md/.well-known/http-message-signatures-directory
            </a>
            . A request with this user agent and no valid signature does not come from yapit.md.
          </p>
          <p className="mt-3">
            Yapit is open source, so anyone can run their own copy. A self-hosted copy sends the same user agent and
            obeys <code>robots.txt</code> the same way, but it cannot sign as yapit.md.
          </p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mb-3">How to block it</h2>
          <p>
            Yapit reads your <code>robots.txt</code> before it requests any page of your site, and on every redirect,
            and fetches nothing it disallows. Its product token is <code>Yapit</code>. To keep it off your whole site:
          </p>
          <pre className="mt-3 overflow-x-auto"><code>{"User-agent: Yapit\nDisallow: /"}</code></pre>
          <ul className="list-disc pl-6 space-y-1 mt-3">
            <li>Rules for <code>User-agent: *</code> apply to yapit when no group names it.</li>
            <li>Yapit keeps a site's <code>robots.txt</code> for up to an hour, so a change can take that long to apply.</li>
            <li>
              While your <code>robots.txt</code> cannot be read (a server error or no answer), yapit fetches nothing
              from your site. One that does not exist (a 404) allows everything.
            </li>
            <li>The reader is told that your <code>robots.txt</code> does not allow yapit to fetch the page.</li>
            <li>
              When your bot protection challenges yapit, yapit does not try to get past it, in disguise or otherwise,
              and tells the reader that your bot protection blocked it.
            </li>
          </ul>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mb-3">Contact</h2>
          <p>
            Questions or problems with the fetcher? Email{" "}
            <a href="mailto:yapit@mwolf.dev" className="text-primary hover:underline">yapit@mwolf.dev</a>
          </p>
        </section>
      </div>
    </div>
  );
};

export default BotPage;

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

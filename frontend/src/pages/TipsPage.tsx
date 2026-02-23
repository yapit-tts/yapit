import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router";
import { ChevronDown, Copy, Check } from "lucide-react";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { SHOWCASE_DOCS } from "@/config/showcase";
import extractionPrompt from "../../../yapit/gateway/document/prompts/extraction.txt?raw";

const codeClass = "text-sm font-mono px-1.5 py-0.5 rounded" as const;
const codeStyle = { background: "var(--muted-brown)" } as const;

const sections = [
  { id: "getting-started", label: "Getting started" },
  { id: "showcase", label: "Try it out" },
  { id: "controls", label: "Controls" },
  { id: "local-tts", label: "Local TTS" },
  { id: "premium-voices", label: "Premium voices" },
  { id: "document-processing", label: "Document processing" },
  { id: "billing", label: "Billing & quota" },
  { id: "faq", label: "FAQ" },
] as const;

const kbdClass = codeClass;

const extLink = (href: string, children: React.ReactNode) => (
  <a href={href} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">{children}</a>
);

const FAQ_ITEMS: { q: string; a: React.ReactNode }[] = [
  {
    q: "Can I use Yapit on my phone?",
    a: "Yes. Premium voices and the hosted Kokoro (Cloud) voices work on any device. The free local voices are desktop-only since they need WebGPU.",
  },
  {
    q: "Does it work offline?",
    a: <>No, Yapit is a web app. But it's fully open source and self-hostable — you can <a href="https://github.com/yapit-tts/yapit#self-hosting" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">run your own instance</a>.</>,
  },
  {
    q: "Are there any usage limits?",
    a: <>Local Kokoro voices are always unlimited, even on the free tier. On paid plans, cloud Kokoro voices are also unlimited. Premium voices have a monthly allowance that depends on your plan — unused hours <Link to="/tips#billing" className="text-primary hover:underline">roll over</Link>. AI document processing has a separate allowance.</>,
  },
  {
    q: "Do I need an account?",
    a: "No — you can use local voices without signing up. But creating an account gives you document sync across devices and more document storage. Subscribing to any paid plan permanently increases your storage limit, even if you cancel later.",
  },
];

const FaqItem = ({ q, a }: { q: string; a: React.ReactNode }) => {
  const [open, setOpen] = useState(false);
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger asChild>
        <button className="w-full flex items-center justify-between py-4 text-left cursor-pointer group">
          <span className="font-medium pr-4">{q}</span>
          <ChevronDown className={cn(
            "h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-200",
            open && "rotate-180",
          )} />
        </button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <p className="text-muted-foreground pb-4">{a}</p>
      </CollapsibleContent>
    </Collapsible>
  );
};

const CopyButton = ({ text }: { text: string }) => {
  const [copied, setCopied] = useState(false);

  const handleCopy = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <button
      onClick={handleCopy}
      className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
      title="Copy to clipboard"
    >
      {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      {copied ? "Copied" : "Copy"}
    </button>
  );
};

const TipsPage = () => {
  const { hash } = useLocation();
  const [promptOpen, setPromptOpen] = useState(false);

  useEffect(() => {
    if (!hash) return;
    const el = document.querySelector(hash);
    if (el) el.scrollIntoView({ behavior: "smooth" });
  }, [hash]);

  return (
    <div className="container max-w-4xl mx-auto py-8 px-6">
      <h1 className="text-4xl font-bold mb-2">Tips</h1>
      <p className="text-lg text-muted-foreground mb-6">
        Get the most out of Yapit
      </p>

      <nav className="flex flex-wrap gap-2 mb-10">
        {sections.map(({ id, label }) => (
          <a
            key={id}
            href={`#${id}`}
            className="text-sm px-3 py-1.5 rounded-full border hover:bg-muted/50 transition-colors"
          >
            {label}
          </a>
        ))}
      </nav>

      <section id="getting-started" className="mb-12 scroll-mt-24">
        <h2 className="text-2xl font-semibold mb-4">Getting started</h2>
        <p className="text-muted-foreground mb-3">
          Paste a URL, upload a PDF, or type text directly. Yapit converts it into a document
          in your library.
        </p>
        <p className="text-muted-foreground mb-3">
          Press <kbd className={kbdClass} style={codeStyle}>Space</kbd> or click the play button
          to start listening. The text highlights as it's read aloud. Click any paragraph to jump there.
        </p>
        <p className="text-muted-foreground mb-3">
          For longer documents, open the outliner
          (<kbd className={kbdClass} style={codeStyle}>o</kbd>) to see
          the section structure. You can collapse sections to focus the playbar or exclude them completely from auto-play if you want to skip them (right-click/long-press).
        </p>
        <p className="text-muted-foreground">
          You can run the english Kokoro models entirely in your browser — for free, no account needed.
        </p>
      </section>

      <section id="showcase" className="mb-12 scroll-mt-24">
        <h2 className="text-2xl font-semibold mb-4">Try it out</h2>
        <p className="text-muted-foreground">
          Try any voice for free with these already ai-transformed documents:{" "}
          {SHOWCASE_DOCS.map((doc, i) => (
            <span key={doc.id}>
              <Link to={`/listen/${doc.id}`} className="text-primary font-medium hover:underline">
                {doc.title}
              </Link>
              {i < SHOWCASE_DOCS.length - 1 && " and "}
            </span>
          ))}.
        </p>
      </section>

      <section id="controls" className="mb-12 scroll-mt-24">
        <h2 className="text-2xl font-semibold mb-4">Controls</h2>

        <h3 className="text-xl font-semibold mb-3">Keyboard shortcuts</h3>
        <p className="text-muted-foreground mb-3">
          Press <kbd className={kbdClass} style={codeStyle}>?</kbd> while reading a document to see all shortcuts.
        </p>
        <div className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm mb-6">
          {([
            ["Space", "Play / pause"],
            ["j ↓", "Next block"],
            ["k ↑", "Previous block"],
            ["l →", "Speed up"],
            ["h ←", "Speed down"],
            ["m", "Mute / unmute"],
            ["+ / =", "Volume up"],
            ["-", "Volume down"],
            ["s", "Toggle sidebar"],
            ["o", "Toggle outliner"],
            ["r", "Back to reading"],
          ] as const).map(([keys, action]) => (
            <div key={keys} className="contents">
              <kbd className={kbdClass} style={codeStyle}>{keys}</kbd>
              <span className="text-muted-foreground">{action}</span>
            </div>
          ))}
        </div>

        <h3 className="text-xl font-semibold mb-3">Headphone & media controls</h3>
        <p className="text-muted-foreground">
          Bluetooth headphones and media keys work out of the box.
          Play/pause, skip forward, and skip back are supported
          through your device's standard media controls.
        </p>
      </section>

      <section id="local-tts" className="mb-12 scroll-mt-24">
        <h2 className="text-2xl font-semibold mb-4">Local text-to-speech</h2>
        <p className="text-muted-foreground mb-4">
          Yapit can synthesize speech directly in your browser
          using {extLink("https://github.com/hexgrad/kokoro/tree/main/kokoro.js", "Kokoro.js")}.
          English voices are available for free. The model (~80 MB) downloads from HuggingFace on first use
          and is cached by your browser. Desktop only.
        </p>

        <h3 className="text-xl font-semibold mb-3 mt-6">WebGPU browser support</h3>
        <p className="text-muted-foreground mb-3">
          Local TTS uses WebGPU for fast GPU-accelerated inference. When WebGPU isn't available,
          it falls back to WebAssembly (CPU), which is slower but functional.
        </p>
        <ul className="list-disc list-inside text-muted-foreground space-y-2 ml-2">
          <li>
            <strong className="text-foreground">Chrome / Edge 113+</strong> works out of the box.
            On Linux, you may need <code className={codeClass} style={codeStyle}>chrome://flags/#enable-vulkan</code>
          </li>
          <li>
            <strong className="text-foreground">Brave</strong> needs <code className={codeClass} style={codeStyle}>brave://flags/#enable-vulkan</code> and <code className={codeClass} style={codeStyle}>brave://flags/#enable-unsafe-webgpu</code> enabled.
            If model downloads fail, check that Brave Shields or an ad-blocker isn't blocking HuggingFace
          </li>
          <li>
            <strong className="text-foreground">Firefox 141+</strong> ships WebGPU on Windows and macOS (ARM).
            On Linux, it's available in Nightly but{" "}
            {extLink(
              "https://mozillagfx.wordpress.com/2025/07/15/shipping-webgpu-on-windows-in-firefox-141/",
              "not yet in stable"
            )}{" "}
            (as of early 2026).
            You can enable it via <code className={codeClass} style={codeStyle}>about:config</code> → <code className={codeClass} style={codeStyle}>dom.webgpu.enabled</code>
          </li>
          <li>
            <strong className="text-foreground">Safari 18+</strong> supported on macOS
          </li>
        </ul>

        <p className="text-muted-foreground mt-4">
          You can check your browser's support at {extLink("https://webgpureport.org", "webgpureport.org")}.
        </p>

        <h3 className="text-xl font-semibold mb-3 mt-6">Troubleshooting</h3>
        <ul className="list-disc list-inside text-muted-foreground space-y-2 ml-2">
          <li><strong className="text-foreground">No audio, no error?</strong> Check the browser console (F12). Usually an ad-blocker blocking HuggingFace or missing GPU drivers</li>
          <li><strong className="text-foreground">Very slow?</strong> You're likely on the WASM fallback. Enable WebGPU for faster processing</li>
        </ul>
      </section>

      <section id="premium-voices" className="mb-12 scroll-mt-24">
        <h2 className="text-2xl font-semibold mb-4">Premium voices</h2>
        <p className="text-muted-foreground mb-3">
          Premium voices are powered by {extLink("https://inworld.ai/tts", "Inworld TTS 1.5")},
          with 65 voices across 15 languages. They run server-side and sound more natural
          than local synthesis. Available on Plus and Max plans.
        </p>
        <p className="text-muted-foreground mb-3">
          Usage is measured in voice characters (the text sent for synthesis).
          Estimates are based on typical reading speed; your actual hours
          will vary with content density and speaking rate.
        </p>
        <p className="text-muted-foreground">
          <strong className="text-foreground">TTS-1.5-Max</strong> is the higher-quality variant,
          with better stability, more natural multilingual pronunciation, and fewer edge-case
          artifacts. It uses 2x the voice character quota.{" "}
          <strong className="text-foreground">TTS-1.5-Mini</strong> is optimized for speed at half the cost,
          and still sounds great for most content.
        </p>
      </section>

      <section id="document-processing" className="mb-12 scroll-mt-24">
        <h2 className="text-2xl font-semibold mb-4">Document processing</h2>
        <p className="text-muted-foreground mb-3">
          When you add a document, Yapit converts it into structured markdown
          for reading and listening. How that happens depends on the input.
        </p>
        <p className="text-muted-foreground mb-3">
          Website URLs are converted
          with {extLink("https://github.com/adbar/trafilatura", "trafilatura")}.
          If the page requires JavaScript to render, Yapit automatically re-fetches it
          with a {extLink("https://playwright.dev/", "headless browser")} for better extraction.
          arXiv links get special treatment
          via {extLink("https://github.com/tonydavis629/markxiv", "markxiv")}, which converts papers
          directly from their LaTeX source for better fidelity.
          PDFs without AI transform are extracted
          with {extLink("https://pymupdf.readthedocs.io/", "PyMuPDF")}.
        </p>

        <h3 id="ai-transform" className="text-xl font-semibold mb-3 mt-6 scroll-mt-24">AI transform</h3>
        <p className="text-muted-foreground mb-3">
          With AI transform enabled, PDFs are run
          through {extLink("https://ai.google.dev/gemini-api", "Gemini 3.5 Flash")} for
          page-by-page text extraction
          and {extLink("https://github.com/opendatalab/DocLayout-YOLO", "DocLayout-YOLO")} for
          figure detection. This handles complex layouts, tables, and math much
          better than plain extraction.
        </p>
        <p className="text-muted-foreground mb-3">
          Usage is measured in AI tokens (the processing cost of the transformation).
          Estimates are based on typical academic content; pages with dense
          tables or many figures may use more.
        </p>
        <p className="text-muted-foreground mb-3">
          Pages that finished extracting are <strong className="text-foreground">cached</strong>.
          If you re-process a document or accidentally close the tab mid-extraction, already-finished pages
          load instantly and won't count toward your usage again.
        </p>

        <h3 id="extraction-prompt" className="text-xl font-semibold mb-3 mt-6 scroll-mt-24">Extraction prompt</h3>
        <p className="text-muted-foreground mb-4">
          This is the exact prompt Yapit sends to Gemini for each page. It tells the model
          how to produce clean markdown and when to use
          {" "}<code className={codeClass} style={codeStyle}>&lt;yap-show&gt;</code>,{" "}
          <code className={codeClass} style={codeStyle}>&lt;yap-speak&gt;</code>, and{" "}
          <code className={codeClass} style={codeStyle}>&lt;yap-cap&gt;</code> tags
          to separate what's displayed from what's read aloud.
          You can use it with any LLM and paste the output straight into Yapit.
        </p>
        <Collapsible open={promptOpen} onOpenChange={setPromptOpen}>
          <CollapsibleTrigger asChild>
            <button className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors cursor-pointer mb-2">
              <ChevronDown className={cn(
                "h-3.5 w-3.5 transition-transform duration-200",
                promptOpen && "rotate-180",
              )} />
              {promptOpen ? "Hide prompt" : "Show full prompt"}
            </button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="relative">
              <div className="absolute top-2 right-2">
                <CopyButton text={extractionPrompt} />
              </div>
              <pre className="text-xs leading-relaxed p-4 rounded-lg border bg-muted/30 overflow-x-auto max-h-[600px] overflow-y-auto whitespace-pre-wrap break-words">
                {extractionPrompt}
              </pre>
            </div>
          </CollapsibleContent>
        </Collapsible>
      </section>

      <section id="billing" className="mb-12 scroll-mt-24">
        <h2 className="text-2xl font-semibold mb-4">Billing & quota</h2>
        <p className="text-muted-foreground mb-3">
          Each billing period gives you a fresh quota of voice characters and AI tokens.
          Your usage draws from this quota throughout the period.
        </p>
        <p className="text-muted-foreground">
          On paid plans, whatever you don't use rolls over to the next period, up to
          1M voice characters and 10M AI tokens. Rollover is consumed after your fresh quota runs out,
          so nothing goes to waste.
        </p>
      </section>

      <section id="faq" className="mb-12 scroll-mt-24">
        <h2 className="text-2xl font-semibold mb-2">FAQ</h2>
        <div className="divide-y">
          {FAQ_ITEMS.map((item) => (
            <FaqItem key={item.q} q={item.q} a={item.a} />
          ))}
        </div>
      </section>
    </div>
  );
};

export default TipsPage;

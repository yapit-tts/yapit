import { useEffect } from "react";
import { useLocation } from "react-router";

const codeClass = "text-sm font-mono px-1.5 py-0.5 rounded" as const;
const codeStyle = { background: "var(--muted-brown)" } as const;

const sections = [
  { id: "local-tts", label: "Local TTS" },
  { id: "premium-voices", label: "Premium voices" },
  { id: "document-processing", label: "Document processing" },
  { id: "billing", label: "Billing & quota" },
] as const;

const extLink = (href: string, children: React.ReactNode) => (
  <a href={href} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">{children}</a>
);

const TipsPage = () => {
  const { hash } = useLocation();

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
          with {extLink("https://github.com/microsoft/markitdown", "MarkItDown")}.
          If the page requires JavaScript to render, Yapit automatically re-fetches it
          with a headless browser.
          arXiv links get special treatment
          via {extLink("https://github.com/tonydavis629/markxiv", "markxiv")}, which converts papers
          directly from their LaTeX source for better fidelity.
          PDFs without AI transform are also processed
          with MarkItDown.
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
        <p className="text-muted-foreground">
          Pages that finished extracting are <strong className="text-foreground">cached</strong>.
          If you re-process a document or accidentally close the tab mid-extraction, already-finished pages
          load instantly and won't count toward your usage again.
        </p>
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

      {/* TODO: Getting Started section */}
      {/* TODO: Document Preprocessing prompts */}
      {/* TODO: FAQ */}
    </div>
  );
};

export default TipsPage;

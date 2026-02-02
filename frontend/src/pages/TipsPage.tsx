const codeClass = "text-sm font-mono px-1.5 py-0.5 rounded" as const;
const codeStyle = { background: "var(--muted-brown)" } as const;

const TipsPage = () => {
  return (
    <div className="container max-w-4xl mx-auto py-8 px-6">
      <h1 className="text-4xl font-bold mb-2">Tips</h1>
      <p className="text-lg text-muted-foreground mb-8">
        Get the most out of Yapit
      </p>

      <section className="mb-8">
        <h2 className="text-2xl font-semibold mb-4">Accidentally closed the tab while processing?</h2>
        <p className="text-muted-foreground">
          Don't worry, your progress isn't lost. Pages that finished extracting are cached.
          When you retry, those pages load instantly and won't count toward your usage limit again.
        </p>
      </section>

      <section id="local-tts" className="mb-8 scroll-mt-24">
        <h2 className="text-2xl font-semibold mb-4">Local text-to-speech</h2>
        <p className="text-muted-foreground mb-4">
          Yapit can synthesize speech directly in your browser
          using <a href="https://github.com/hexgrad/kokoro/tree/main/kokoro.js" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">Kokoro.js</a>.
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
            <a href="https://mozillagfx.wordpress.com/2025/07/15/shipping-webgpu-on-windows-in-firefox-141/" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
              not yet in stable
            </a> (as of early 2026).
            You can enable it via <code className={codeClass} style={codeStyle}>about:config</code> → <code className={codeClass} style={codeStyle}>dom.webgpu.enabled</code>
          </li>
          <li>
            <strong className="text-foreground">Safari 18+</strong> supported on macOS
          </li>
        </ul>

        <p className="text-muted-foreground mt-4">
          You can check your browser's support at{" "}
          <a href="https://webgpureport.org" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
            webgpureport.org
          </a>.
        </p>

        <h3 className="text-xl font-semibold mb-3 mt-6">Troubleshooting</h3>
        <ul className="list-disc list-inside text-muted-foreground space-y-2 ml-2">
          <li><strong className="text-foreground">No audio, no error?</strong> Check the browser console (F12). Usually an ad-blocker blocking HuggingFace or missing GPU drivers</li>
          <li><strong className="text-foreground">Very slow?</strong> You're likely on the WASM fallback. Enable WebGPU for faster processing</li>
        </ul>
      </section>

      {/* TODO: Getting Started section */}
      {/* TODO: How billing works (subscription quota, rollover, negative balance/debt) */}
      {/* TODO: Document Preprocessing prompts */}
      {/* TODO: FAQ */}
    </div>
  );
};

export default TipsPage;

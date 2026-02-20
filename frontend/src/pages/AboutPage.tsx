import { Link } from "react-router";
import { Github, Headphones, Globe, BookOpen, Mic } from "lucide-react";

const AboutPage = () => {
  return (
    <div className="container max-w-4xl mx-auto py-8 px-6">
      <div className="flex items-start justify-between mb-10">
        <div>
          <h1 className="text-4xl font-bold mb-2">About Yapit</h1>
          <p className="text-lg text-muted-foreground">
            Open-source text-to-speech for reading documents, web pages, and
            text
          </p>
        </div>
        <img
          src="/favicon.svg"
          alt=""
          className="h-16 w-16 shrink-0 ml-6 mt-1"
        />
      </div>

      {/* Why */}
      <section className="mb-10">
        <h2 className="text-2xl font-semibold mb-4">Why Yapit Exists</h2>
        <p className="text-muted-foreground mb-4">
          I spend a lot of time staring at my computer screen, reading 
          research papers, books, blogposts, long-form articles. Finding the
          energy to sit down and focus on reading all that content is hard. I
          find that listening makes it much easier to get started, keep focused
          and allows me to take my eyes off the screen for a bit and do other
          things while listening.
        </p>
        <p className="text-muted-foreground mb-4">
          However, existing text-to-speech tools were either painfully robotic
          or unreasonably expensive. And, more importantly, <i>none</i> of them could reliably
          handle the documents I actually cared about: PDFs with math,
          citations, page numbers, code blocks, etc. — messy real-world content.
        </p>
        <p className="text-muted-foreground">
          So I built Yapit. Paste a URL or drop a file and it handles the rest.
          AI is used, not to summarize/slopcastify the content, but to present it in a faithful way, while making it a pleasure to listen to.
        </p>
      </section>

      {/* What it does */}
      <section className="mb-10">
        <h2 className="text-2xl font-semibold mb-6">What You Get</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
          <div className="flex gap-3">
            <BookOpen className="h-5 w-5 text-primary mt-1 shrink-0" />
            <div>
              <h3 className="font-medium mb-1">Make documents listenable</h3>
              <p className="text-sm text-muted-foreground">
                Complex content gets transformed into Markdown: Structure is
                preserved but read in a natural way.
              </p>
            </div>
          </div>
          <div className="flex gap-3">
            <Mic className="h-5 w-5 text-primary mt-1 shrink-0" />
            <div>
              <h3 className="font-medium mb-1">120+ voices</h3>
              <p className="text-sm text-muted-foreground">
                State of the art voices by{" "}
                <a href="https://inworld.ai/" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">Inworld</a>
                {" "}and{" "}
                <a href="https://huggingface.co/hexgrad/Kokoro-82M" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">Kokoro</a>
                {" "}models that run locally on your PC.
              </p>
            </div>
          </div>
          <div className="flex gap-3">
            <Globe className="h-5 w-5 text-primary mt-1 shrink-0" />
            <div>
              <h3 className="font-medium mb-1">15 languages</h3>
              <p className="text-sm text-muted-foreground">
                English, French, Japanese, Spanish, German, Italian, Portuguese,
                Chinese, Korean, Russian, and more.
              </p>
            </div>
          </div>
          <div className="flex gap-3">
            <Headphones className="h-5 w-5 text-primary mt-1 shrink-0" />
            <div>
              <h3 className="font-medium mb-1">Crafted for comfort</h3>
              <p className="text-sm text-muted-foreground">
                Text highlighting that follows along, keyboard shortcuts,
                adjustable speed, and dark mode themes for late-night sessions.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Open source */}
      <section className="mb-10">
        <h2 className="text-2xl font-semibold mb-4">Open Source</h2>
        <p className="text-muted-foreground mb-4">
          Yapit is fully open source and self-hostable. Contributions welcome:
        </p>
        <a
          href="https://github.com/yapit-tts/yapit"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 text-primary hover:underline"
        >
          <Github className="h-5 w-5" />
          github.com/yapit-tts/yapit
        </a>
      </section>

      {/* Legal */}
      <section className="mb-12">
        <h2 className="text-2xl font-semibold mb-4">Legal</h2>
        <div className="flex gap-6 text-muted-foreground mb-6">
          <Link to="/terms" className="hover:text-foreground transition-colors">
            Terms of Service
          </Link>
          <Link
            to="/privacy"
            className="hover:text-foreground transition-colors"
          >
            Privacy Policy
          </Link>
        </div>

        {/* Imprint (ECG §5, MedienG §25) */}
        <div className="text-sm text-muted-foreground">
          <h3 className="font-medium text-foreground mb-2">Imprint</h3>
          <p>Maximilian Wolf</p>
          <p>Carl Moll Gasse 8, 2301 Oberhausen, Austria</p>
          <p>yapit@mwolf.dev</p>
          <p className="mt-2">Text-to-speech platform (Einzelunternehmen)</p>
        </div>
      </section>
    </div>
  );
};

export default AboutPage;

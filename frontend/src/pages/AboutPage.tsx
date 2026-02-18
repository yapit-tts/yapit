import { Link } from "react-router";
import { Github } from "lucide-react";

const AboutPage = () => {
  return (
    <div className="container max-w-4xl mx-auto py-8 px-6">
      <h1 className="text-4xl font-bold mb-2">About Yapit</h1>
      <p className="text-lg text-muted-foreground mb-8">
        Open-source text-to-speech for reading documents, web pages, and text
      </p>

      {/* Source code */}
      <section className="mb-12">
        <h2 className="text-2xl font-semibold mb-4">Source Code</h2>
        <p className="text-muted-foreground mb-4">
          Yapit is open source. View the code, report issues, or contribute on GitHub.
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
          <Link to="/privacy" className="hover:text-foreground transition-colors">
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

import { useState, useEffect } from "react";
import { Link } from "react-router";
import { X } from "lucide-react";

const DISMISSED_KEY = "yapit_getting_started_dismissed";

// TODO: Replace with showcase.json config once documents are created
const SHOWCASE_DOCS = [
  { id: "placeholder-blog", title: "Blog post" },
  { id: "placeholder-pdf", title: "PDF with figures" },
  { id: "placeholder-image", title: "Image" },
];

export function GettingStarted() {
  const [dismissed, setDismissed] = useState(true); // Start hidden to prevent flash

  useEffect(() => {
    setDismissed(localStorage.getItem(DISMISSED_KEY) === "true");
  }, []);

  const handleDismiss = () => {
    localStorage.setItem(DISMISSED_KEY, "true");
    setDismissed(true);
  };

  if (dismissed) {
    return null;
  }

  return (
    <div className="mt-4 flex items-center justify-center gap-2 text-sm text-muted-foreground">
      <span>Try:</span>
      {SHOWCASE_DOCS.map((doc, i) => (
        <span key={doc.id}>
          <Link to={`/d/${doc.id}`} className="text-foreground hover:underline">
            {doc.title}
          </Link>
          {i < SHOWCASE_DOCS.length - 1 && <span className="ml-2">·</span>}
        </span>
      ))}
      <button
        onClick={handleDismiss}
        className="ml-1 p-0.5 text-muted-foreground/50 hover:text-muted-foreground"
        title="Dismiss"
      >
        <X className="h-3 w-3" />
      </button>
    </div>
  );
}

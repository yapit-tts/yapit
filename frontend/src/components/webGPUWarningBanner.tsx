import { useState, useEffect } from "react";
import { X, AlertTriangle } from "lucide-react";
import { Link } from "react-router";
import { useCanUseLocalTTS } from "@/hooks/useCanUseLocalTTS";
import { useSubscription } from "@/hooks/useSubscription";

const DISMISSED_KEY = "yapit_webgpu_warning_dismissed";

export function WebGPUWarningBanner() {
  const canUseLocalTTS = useCanUseLocalTTS();
  const { tier, isLoading } = useSubscription();
  const [dismissed, setDismissed] = useState(true); // Start hidden to prevent flash

  useEffect(() => {
    setDismissed(localStorage.getItem(DISMISSED_KEY) === "true");
  }, []);

  const handleDismiss = () => {
    localStorage.setItem(DISMISSED_KEY, "true");
    setDismissed(true);
  };

  if (isLoading || canUseLocalTTS !== false || tier !== "free" || dismissed) {
    return null;
  }

  return (
    <div className="flex items-center justify-between gap-4 bg-muted-warm px-4 py-3 border-b border-border">
      <div className="flex items-center gap-3 text-sm">
        <AlertTriangle className="h-4 w-4 text-accent-warning shrink-0" />
        <p className="text-foreground">
          Your device may not support free local processing.
          Listen to our{" "}
          <Link to="/tips#showcase" className="text-primary font-medium hover:underline">
            free examples
          </Link>
          ,{" "}
          <Link to="/subscription" className="text-primary font-medium hover:underline">
            upgrade
          </Link>
          , or{" "}
          <Link to="/tips#local-tts" className="underline hover:no-underline">
            learn more
          </Link>.
        </p>
      </div>
      <button
        onClick={handleDismiss}
        className="shrink-0 p-2 min-w-11 min-h-11 flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-accent rounded-md transition-colors"
        title="Don't show again"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}

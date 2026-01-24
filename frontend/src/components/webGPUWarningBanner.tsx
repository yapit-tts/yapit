import { useState, useEffect } from "react";
import { X, AlertTriangle } from "lucide-react";
import { Link } from "react-router";
import { useHasWebGPU } from "@/hooks/useWebGPU";
import { useSubscription } from "@/hooks/useSubscription";

const DISMISSED_KEY = "yapit_webgpu_warning_dismissed";

export function WebGPUWarningBanner() {
  const hasWebGPU = useHasWebGPU();
  const { tier, isLoading } = useSubscription();
  const [dismissed, setDismissed] = useState(true); // Start hidden to prevent flash

  useEffect(() => {
    setDismissed(localStorage.getItem(DISMISSED_KEY) === "true");
  }, []);

  const handleDismiss = () => {
    localStorage.setItem(DISMISSED_KEY, "true");
    setDismissed(true);
  };

  // Don't show if: loading, has WebGPU, has paid plan, or dismissed
  if (isLoading || hasWebGPU === undefined || hasWebGPU || tier !== "free" || dismissed) {
    return null;
  }

  // TODO make sure all these links are correct once we add the sections
  return (
    <div className="flex items-center justify-between gap-4 bg-muted-warm px-4 py-3 border-b border-border">
      <div className="flex items-center gap-3 text-sm">
        <AlertTriangle className="h-4 w-4 text-accent-warning shrink-0" />
        <p className="text-foreground">
          Your device may not support free local processing. Try{" "}
          <Link to="/tips#showcase" className="text-primary font-medium hover:underline">
            these examples
          </Link>{" "}
          for free,{" "}
          <Link to="/subscription" className="text-primary font-medium hover:underline">
            upgrade
          </Link>
          , or{" "}
          <Link to="/tips#webgpu" className="underline hover:no-underline">
            learn more
          </Link>.
        </p>
      </div>
      <button
        onClick={handleDismiss}
        className="shrink-0 p-2 min-w-[44px] min-h-[44px] flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-accent rounded-md transition-colors"
        title="Don't show again"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}

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
    <div className="flex items-center justify-between gap-4 bg-amber-500/10 px-4 py-3 border-b border-amber-500/20">
      <div className="flex items-center gap-3 text-sm">
        <AlertTriangle className="h-4 w-4 text-amber-600 shrink-0" />
        <p className="text-amber-800 dark:text-amber-200">
          Your device may not support free local processing.{" "}
          <Link to="/tips#webgpu" className="underline hover:no-underline">
            Learn more
          </Link>
            , try{" "}
          <Link to="/tips#showcase" className="underline hover:no-underline">
            these examples
          </Link>{" "}
          for free, or{" "}
          <Link to="/subscription" className="underline hover:no-underline">
            upgrade.
          </Link>{" "}
        </p>
      </div>
      <button
        onClick={handleDismiss}
        className="shrink-0 p-1 text-amber-600/70 hover:text-amber-600"
        title="Don't show again"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}

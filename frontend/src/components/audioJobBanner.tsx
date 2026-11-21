import { useState } from "react";
import { Link } from "react-router";
import { AlertTriangle, AudioLines, Square, X } from "lucide-react";
import { ProgressLine } from "@/components/audioParts";
import { OPEN_AUDIO_PANEL_EVENT, audioVariant } from "@/lib/audioVariant";
import { Button } from "@/components/ui/button";
import type { AudioJob } from "@/lib/audioJob";

const numberFormat = new Intl.NumberFormat();

/**
 * A running job's progress and its stop button; once it stops short, why, if this tab saw it run.
 * A job that finished, or ended before the page loaded, stays quiet: its outcome is the bar's cached blocks.
 */
export function AudioJobBanner({ job, onCancel }: { job: AudioJob | null; onCancel: () => Promise<void> }) {
  const [sawRunning, setSawRunning] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const status = job?.status;

  if (status === "running" && (!sawRunning || dismissed)) {
    setSawRunning(true);
    setDismissed(false);
  }

  if (!job || dismissed || job.status === "cancelled" || job.status === "done") return null;
  if (status !== "running" && !sawRunning) return null;

  const variant = audioVariant();
  if (variant === "b" && status === "running") return null;
  if (variant !== null) {
    return <VariantBanner job={job} variant={variant} onCancel={onCancel} onDismiss={() => setDismissed(true)} />;
  }

  const progress = `${numberFormat.format(job.cached_blocks)} of ${numberFormat.format(job.total_blocks)} blocks`;
  const isProblem = job.status !== "running";
  const Icon = isProblem ? AlertTriangle : AudioLines;

  return (
    <div
      role="status"
      className={`flex flex-wrap items-center justify-center gap-x-2 gap-y-1 mb-3 py-1.5 px-4 rounded-lg text-sm border ${isProblem ? "bg-destructive/10 border-destructive/20" : "bg-muted border-border"}`}
    >
      <Icon className={`h-4 w-4 shrink-0 ${isProblem ? "text-destructive" : "text-primary animate-pulse"}`} />
      <span className="text-foreground font-medium">
        {job.status === "running" ? "Preparing audio" : endedReason(job.status, job.error)}
      </span>
      <span className="text-muted-foreground">·</span>
      <span className="text-muted-foreground tabular-nums">{progress}</span>
      {status === "usage_limit" && (
        <Link to="/subscription" className="text-primary font-medium hover:underline px-1">See plans</Link>
      )}
      {!isProblem ? (
        <Button variant="ghost" size="sm" className="h-9 px-3" onClick={() => void onCancel()}>Stop</Button>
      ) : (
        <button
          onClick={() => setDismissed(true)}
          className="p-2 min-w-11 min-h-11 flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-accent rounded-md transition-colors"
          aria-label="Dismiss"
        >
          <X className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}

function endedReason(status: "usage_limit" | "failed", error: string | null): string {
  switch (status) {
    case "usage_limit": return "Preparing stopped: your plan's characters ran out";
    case "failed": return `Preparing stopped${error ? `: ${error}` : ""}`;
  }
}

/** The variants' line above the controls: why a job stopped short, in all three; while it runs, A's progress with Stop, or C's that opens the panel. */
function VariantBanner({ job, variant, onCancel, onDismiss }: { job: AudioJob; variant: "a" | "b" | "c"; onCancel: () => Promise<void>; onDismiss: () => void }) {
  const count = `${numberFormat.format(job.cached_blocks)} of ${numberFormat.format(job.total_blocks)}`;
  if (job.status !== "running") {
    const reason = job.status === "usage_limit" ? "your plan's characters ran out" : job.error ?? "the server stopped it";
    return (
      <div role="status" className="flex items-center justify-center gap-2 mb-3 text-sm text-muted-foreground">
        <AlertTriangle className="h-4 w-4 shrink-0 text-accent-warning" />
        <span>{variant === "a" ? "Audiobook" : "Audio"} stopped at {count}: {reason}</span>
        {job.status === "usage_limit" && <Link to="/subscription" className="text-primary hover:underline">See plans</Link>}
        <button onClick={onDismiss} className="p-2 rounded-md text-muted-foreground hover:text-primary" aria-label="Dismiss"><X className="h-4 w-4" /></button>
      </div>
    );
  }
  if (variant === "c") {
    return (
      <div role="status" className="flex justify-center mb-2">
        <button
          onClick={() => window.dispatchEvent(new Event(OPEN_AUDIO_PANEL_EVENT))}
          className="flex items-center gap-2 px-2 py-1 rounded-md text-sm text-muted-foreground hover:text-primary transition-colors"
          title="Show which sections are generated"
        >
          <AudioLines className="h-4 w-4" />
          Generating audio <span className="font-mono tabular-nums">{count}</span>
        </button>
      </div>
    );
  }
  return (
    <div role="status" className="flex items-center justify-center gap-3 mb-2 max-w-md mx-auto text-sm text-muted-foreground">
      <AudioLines className="h-4 w-4 shrink-0" />
      <span className="shrink-0">Making audiobook</span>
      <div className="flex-1 min-w-12"><ProgressLine done={job.cached_blocks} total={job.total_blocks} /></div>
      <span className="font-mono tabular-nums shrink-0">{count}</span>
      <Button variant="ghost" size="sm" className="h-8" onClick={() => void onCancel()}><Square />Stop</Button>
    </div>
  );
}

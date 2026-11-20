import { useState } from "react";
import { Link } from "react-router";
import { AlertTriangle, AudioLines, Check, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { AudioJob } from "@/lib/audioJob";

const numberFormat = new Intl.NumberFormat();

/**
 * A running job's progress and its stop button; once it ends, why, if this tab saw it run.
 * A job that ended before the page loaded stays quiet: its outcome is the bar's cached blocks.
 */
export function AudioJobBanner({ job, onCancel }: { job: AudioJob | null; onCancel: () => Promise<void> }) {
  const [sawRunning, setSawRunning] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const status = job?.status;

  if (status === "running" && (!sawRunning || dismissed)) {
    setSawRunning(true);
    setDismissed(false);
  }

  if (!job || dismissed) return null;
  if (status !== "running" && (!sawRunning || status === "cancelled")) return null;

  const progress = `${numberFormat.format(job.cached_blocks)} of ${numberFormat.format(job.total_blocks)} blocks`;
  const ended = status !== "running";
  const isProblem = ended && status !== "done";
  const Icon = status === "done" ? Check : isProblem ? AlertTriangle : AudioLines;

  return (
    <div
      role="status"
      className={`flex flex-wrap items-center justify-center gap-x-2 gap-y-1 mb-3 py-1.5 px-4 rounded-lg text-sm border ${isProblem ? "bg-destructive/10 border-destructive/20" : "bg-muted border-border"}`}
    >
      <Icon className={`h-4 w-4 shrink-0 ${isProblem ? "text-destructive" : status === "done" ? "text-accent-success" : "text-primary animate-pulse"}`} />
      <span className="text-foreground font-medium">
        {status === "running" ? "Preparing audio" : status === "done" ? "Audio prepared" : endedReason(job)}
      </span>
      <span className="text-muted-foreground">·</span>
      <span className="text-muted-foreground tabular-nums">{progress}</span>
      {status === "usage_limit" && (
        <Link to="/subscription" className="text-primary font-medium hover:underline px-1">See plans</Link>
      )}
      {status === "running" ? (
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

function endedReason(job: AudioJob): string {
  switch (job.status) {
    case "usage_limit": return "Preparing stopped: your plan's characters ran out";
    case "daily_limit": return "Preparing stopped at today's limit; start it again tomorrow";
    default: return `Preparing stopped${job.error ? `: ${job.error}` : ""}`;
  }
}

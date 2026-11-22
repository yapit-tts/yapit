import { useState } from "react";
import { Link } from "react-router";
import { AlertTriangle, FileAudio, X } from "lucide-react";
import type { AudioJob } from "@/lib/audioJob";

const numberFormat = new Intl.NumberFormat();

/**
 * An unboxed line above the playback controls: a running job's progress, which opens the panel that holds its Stop;
 * once it stops short, why, if this tab saw it run. A job that finished, or ended before the page loaded, stays quiet:
 * its outcome is the bar's cached blocks.
 */
export function AudioJobBanner({ job, onOpen }: { job: AudioJob | null; onOpen: () => void }) {
  const [sawRunning, setSawRunning] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const status = job?.status;

  if (status === "running" && (!sawRunning || dismissed)) {
    setSawRunning(true);
    setDismissed(false);
  }

  if (!job || dismissed || job.status === "cancelled" || job.status === "done") return null;
  if (status !== "running" && !sawRunning) return null;

  const count = `${numberFormat.format(job.cached_blocks)} of ${numberFormat.format(job.total_blocks)}`;

  if (job.status === "running") {
    return (
      <div role="status" className="flex justify-center mb-2">
        <button onClick={onOpen} className="flex items-center gap-2 px-2 py-1 rounded-md text-sm text-muted-foreground hover:text-primary transition-colors">
          <FileAudio className="h-4 w-4" />
          Generating audio <span className="font-mono tabular-nums">{count}</span>
        </button>
      </div>
    );
  }

  const reason = job.status === "usage_limit"
    ? <>Generating stopped at <span className="font-mono tabular-nums">{count}</span>: your plan's characters ran out. <Link to="/subscription" className="text-primary hover:underline">See plans</Link></>
    : <>Generating stopped: {job.error ?? "the server could not finish it"}</>;
  return (
    <div role="status" className="flex items-start gap-2 mb-3 max-w-2xl mx-auto text-sm text-muted-foreground">
      <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0 text-accent-warning" />
      <span className="flex-1 min-w-0">{reason}</span>
      <button onClick={() => setDismissed(true)} className="-mt-1.5 p-1.5 rounded-md text-muted-foreground hover:text-primary" aria-label="Dismiss">
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}

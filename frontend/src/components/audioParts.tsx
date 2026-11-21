import { Link } from "react-router";
import { Info } from "lucide-react";
import * as PopoverPrimitive from "@radix-ui/react-popover";
import type { AudioSelection } from "@/hooks/useAudioSelection";
import { formatDuration } from "@/lib/sectionIndex";

export const numberFormat = new Intl.NumberFormat();

const linkClass = "text-primary underline decoration-primary/40 underline-offset-2 hover:decoration-primary";

/** A caution beside what it is about: a 2px bar and small muted text, never a filled box. */
export function Note({ children, caution = false }: { children: React.ReactNode; caution?: boolean }) {
  return (
    <p className={`border-l-2 pl-3 text-sm text-muted-foreground ${caution ? "border-accent-warning" : "border-border"}`}>
      {children}
    </p>
  );
}

/** Every reason the ticked sections cannot be made, or would be made only in part, or failed to download, each as a note. */
export function SelectionNotes({ s, making, show = "all" }: { s: AudioSelection; making: string; show?: "all" | "make" | "download" }) {
  const { blocker, shortfall, refusal, totals } = s;
  const exportErrors = show === "make" ? [] : s.exportErrors;
  if (show === "download") return <>{exportErrors.map(({ format, error }) => <Note key={format} caution>{error}</Note>)}</>;
  return (
    <>
      {blocker?.kind === "browser-voice" && (
        <Note caution>
          A voice run on this device keeps its audio in this tab only.{" "}
          <button className={linkClass} onClick={s.useServerKokoro}>Run Kokoro on Cloud</button>
        </Note>
      )}
      {blocker?.kind === "running-elsewhere" && (
        <Note caution>
          You are {making} audio for <Link className={linkClass} to={`/listen/${blocker.documentId}`}>another document</Link>. Stop it there or let it finish first.
        </Note>
      )}
      {blocker?.kind === "not-on-plan" && (
        <Note caution>
          {blocker.kokoro ? "Kokoro on Cloud is" : "This voice is"} not on your plan. <Link className={linkClass} to="/subscription">See plans</Link>
          {blocker.kokoro && ", or run Kokoro on this device to listen"}.
        </Note>
      )}
      {blocker?.kind === "no-characters" && (
        <Note caution>
          No characters are left on your plan this period. <Link className={linkClass} to="/subscription">See plans</Link>
        </Note>
      )}
      {shortfall !== null && (
        <Note caution>
          That needs {numberFormat.format(totals.charactersToSynthesize)} characters and your plan has {numberFormat.format(shortfall)} left, so {making} stops partway.
        </Note>
      )}
      {refusal && <Note caution>{refusal}</Note>}
      {exportErrors.map(({ format, error }) => <Note key={format} caution>{error}</Note>)}
    </>
  );
}

/** The selection's length, and its characters only where the plan counts them. */
export function SelectionMeta({ s }: { s: AudioSelection }) {
  const { totals, estimate, estimateFailed, onServer } = s;
  if (totals.blocks === 0) return <>Nothing ticked</>;
  const length = formatDuration(totals.durationMs);
  if (!onServer || estimate === null) return <>{length}{estimateFailed && " · could not check what is made"}</>;
  const limit = estimate.available_characters;
  if (limit === null || s.blocker !== null || totals.charactersToSynthesize === 0) return <>{length}</>;
  return <>{length} · {numberFormat.format(totals.charactersToSynthesize)} characters, {numberFormat.format(limit)} left</>;
}

/** An explanation one click away: an (i) that opens a short note under it. */
export function InfoHint({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <PopoverPrimitive.Root>
      <PopoverPrimitive.Trigger
        aria-label={label}
        className="p-1 rounded text-muted-foreground hover:text-primary transition-colors"
      >
        <Info className="h-4 w-4" />
      </PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          sideOffset={6}
          className="z-50 max-w-72 rounded-md border bg-background px-3 py-2 text-sm text-foreground data-[state=open]:animate-in data-[state=open]:fade-in-0"
        >
          {children}
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}

/** A thin progress line: an edge track, filled in body ink. */
export function ProgressLine({ done, total }: { done: number; total: number }) {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  return (
    <div className="h-0.5 w-full bg-border rounded-full overflow-hidden" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={done}>
      <div className="h-full bg-foreground/70 transition-[width] duration-150" style={{ width: `${pct}%` }} />
    </div>
  );
}

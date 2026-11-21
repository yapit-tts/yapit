import { useState } from "react";
import * as PopoverPrimitive from "@radix-ui/react-popover";
import { Check, ChevronDown, Download, Loader2, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { VoicePicker } from "@/components/voicePicker";
import { InfoHint, ProgressLine, SelectionMeta, SelectionNotes, numberFormat } from "@/components/audioParts";
import { type AudioSelectionProps, useAudioSelection } from "@/hooks/useAudioSelection";
import { EXPORT_FORMATS } from "@/lib/audioJob";
import { formatDuration } from "@/lib/sectionIndex";

interface DownloadAudioPopoverProps extends AudioSelectionProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The header button that opened it; the popover hangs just below it. */
  anchor: HTMLElement | null;
}

/** Variant B: a popover under the header's audio button, two numbered steps, the sections one click away. */
export function DownloadAudioPopover(props: DownloadAudioPopoverProps) {
  const anchorRef = { current: props.anchor };
  return (
    <PopoverPrimitive.Root open={props.open && props.anchor !== null} onOpenChange={props.onOpenChange}>
      <PopoverPrimitive.Anchor virtualRef={anchorRef as React.RefObject<HTMLElement>} />
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          align="end"
          sideOffset={8}
          collisionPadding={8}
          aria-label="Download audio"
          className="z-50 w-96 max-w-[var(--radix-popover-content-available-width)] max-h-[var(--radix-popover-content-available-height)] overflow-y-auto rounded-md border bg-background p-5 flex flex-col gap-4 data-[state=open]:animate-in data-[state=open]:fade-in-0"
        >
          {props.open && <DownloadAudioForm {...props} />}
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}

function DownloadAudioForm(props: DownloadAudioPopoverProps) {
  const s = useAudioSelection(props, () => {});
  const [showSections, setShowSections] = useState(false);
  const running = s.jobRunsHere && props.job ? props.job : null;
  const tickedCount = s.rows.filter(r => r.ticked).length;
  const sectionsLabel = tickedCount === s.rows.length ? `All ${s.rows.length} sections` : `${tickedCount} of ${s.rows.length} sections`;

  return (
    <>
      <div className="flex items-center gap-1">
        <h2 className="text-lg font-semibold text-foreground">Download audio</h2>
        <InfoHint label="How downloading audio works">
          The server reads the ticked sections aloud first, which carries on with this tab closed and makes playback start without waiting. Then they download as one file with a chapter per section.
        </InfoHint>
      </div>

      <div className="flex flex-col gap-1">
        <div className="flex items-center justify-between gap-2">
          <button
            onClick={() => setShowSections(v => !v)}
            aria-expanded={showSections}
            className="flex items-center gap-1.5 rounded-md py-1 text-sm text-foreground hover:text-primary transition-colors"
          >
            {sectionsLabel}
            <span className="font-mono tabular-nums text-muted-foreground">{formatDuration(s.totals.durationMs)}</span>
            <ChevronDown className={`h-4 w-4 text-muted-foreground transition-transform ${showSections ? "rotate-180" : ""}`} />
          </button>
          <VoicePicker value={props.voiceSelection} onChange={props.onVoiceChange} />
        </div>
        {showSections && (
          <ul aria-label="Sections" className="max-h-[35dvh] overflow-y-auto">
            {s.rows.map(row => (
              <li key={row.id}>
                <label className="flex items-center gap-3 rounded-md px-1 min-h-9 cursor-pointer text-sm hover:bg-accent">
                  <input type="checkbox" checked={row.ticked} onChange={() => s.toggle(row.id)} className="h-4 w-4 shrink-0 accent-primary" />
                  <span className={`flex-1 min-w-0 py-1.5 leading-snug ${row.ticked ? "text-foreground" : "text-muted-foreground"}`}>{row.title}</span>
                  {row.blocksToMake === 0 && <Check className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-label="Made" />}
                  <span className="w-9 text-right font-mono tabular-nums text-muted-foreground shrink-0">{formatDuration(row.durationMs)}</span>
                </label>
              </li>
            ))}
          </ul>
        )}
      </div>

      <ol className="flex flex-col gap-4">
        <Step n={1} title="Make the audio" done={s.allMade}>
          {running ? (
            <div className="flex items-center gap-3" aria-live="polite">
              <div className="flex-1"><ProgressLine done={running.cached_blocks} total={running.total_blocks} /></div>
              <span className="text-sm font-mono tabular-nums text-muted-foreground">{numberFormat.format(running.cached_blocks)} of {numberFormat.format(running.total_blocks)}</span>
              <Button variant="ghost" size="sm" onClick={() => void props.onCancel()}><Square />Stop</Button>
            </div>
          ) : s.allMade ? null : (
            <div className="flex items-center justify-between gap-3">
              <span className="text-sm text-muted-foreground font-mono tabular-nums" aria-live="polite"><SelectionMeta s={s} /></span>
              <Button size="sm" className="shadow-none" onClick={() => void s.start()} disabled={!s.canStart}>
                {s.isStarting && <Loader2 className="animate-spin" />}
                Make
              </Button>
            </div>
          )}
          <div className="flex flex-col gap-2 mt-2 empty:hidden"><SelectionNotes s={s} making="making" show="make" /></div>
        </Step>
        <Step n={2} title="Download">
          <div className="flex gap-2">
            {EXPORT_FORMATS.map(format => {
              const building = props.exportProgress[format]?.building === true;
              return (
                <Button
                  key={format}
                  size="sm"
                  variant={s.allMade ? "default" : "outline"}
                  className="shadow-none"
                  title={format === "m4b" ? "An audiobook file with chapters, for Apple Books and most audiobook players" : "Plays everywhere; chapters show in some players"}
                  onClick={() => s.download(format)}
                  disabled={!s.allMade || building}
                >
                  {building ? <Loader2 className="animate-spin" /> : <Download />}
                  {format.toUpperCase()}
                </Button>
              );
            })}
          </div>
          <div className="flex flex-col gap-2 mt-2 empty:hidden"><SelectionNotes s={s} making="making" show="download" /></div>
        </Step>
      </ol>
    </>
  );
}

function Step({ n, title, done = false, children }: { n: number; title: string; done?: boolean; children: React.ReactNode }) {
  return (
    <li className="grid grid-cols-[1.25rem_1fr] gap-x-2 gap-y-1.5">
      <span className="font-mono tabular-nums text-sm text-muted-foreground leading-6">{done ? <Check className="h-4 w-4 mt-1" aria-label="Done" /> : n}</span>
      <span className="text-sm font-medium text-foreground leading-6">{title}</span>
      <span />
      <div>{children}</div>
    </li>
  );
}

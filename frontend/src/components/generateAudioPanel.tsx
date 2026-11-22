import { Link } from "react-router";
import { AudioLines, Check, Download, Info, Loader2, Square } from "lucide-react";
import * as PopoverPrimitive from "@radix-ui/react-popover";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { VoicePicker } from "@/components/voicePicker";
import { type AudioSelection, type AudioSelectionProps, type RowState, useAudioSelection } from "@/hooks/useAudioSelection";
import { EXPORT_FORMATS } from "@/lib/audioJob";
import { formatDuration } from "@/lib/sectionIndex";

const numberFormat = new Intl.NumberFormat();

const linkClass = "text-primary underline decoration-primary/40 underline-offset-2 hover:decoration-primary";

/** The house overlay: the page's own ground, a hairline, no shadow. */
const overlayClass = "z-50 max-w-72 rounded-md border bg-background px-3 py-2 text-sm text-foreground data-[state=delayed-open]:animate-in data-[state=delayed-open]:fade-in-0 data-[state=instant-open]:animate-in data-[state=instant-open]:fade-in-0 data-[state=open]:animate-in data-[state=open]:fade-in-0";

interface GenerateAudioPanelProps extends AudioSelectionProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** A panel at the right edge, where the outline opens: the sections to generate, each with its own progress, and the actions at its foot. */
export function GenerateAudioPanel(props: GenerateAudioPanelProps) {
  return (
    <Sheet open={props.open} onOpenChange={props.onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-md gap-0 shadow-none">
        {props.open && <GenerateAudioForm {...props} />}
      </SheetContent>
    </Sheet>
  );
}

function GenerateAudioForm(props: GenerateAudioPanelProps) {
  const s = useAudioSelection(props);
  const running = s.jobRunsHere && props.job ? props.job : null;
  const allTicked = s.rows.every(r => r.ticked);

  return (
    <>
      <div className="flex flex-col gap-3 px-5 pt-5 pb-3 border-b">
        <div className="flex items-center gap-1 pr-8">
          <SheetTitle className="text-lg font-semibold text-foreground">Generate audio</SheetTitle>
          <InfoHint label="What generating audio does">
            The server reads the ticked sections aloud ahead of time, and carries on with this tab closed. Playback of them then starts without waiting, and you can save them as one file with a chapter per section.
          </InfoHint>
        </div>
        <SheetDescription className="sr-only">Pick the sections and the voice, generate their audio, then save it as one file.</SheetDescription>
        <div className="flex items-center justify-between gap-2">
          <VoicePicker value={props.voiceSelection} onChange={props.onVoiceChange} />
          <Button variant="ghost" size="sm" className="text-muted-foreground" onClick={() => s.setAll(!allTicked)}>
            {allTicked ? "Tick none" : "Tick all"}
          </Button>
        </div>
      </div>

      <ul aria-label="Sections" className="flex-1 overflow-y-auto px-3 py-2">
        {s.rows.map(row => <SectionRow key={row.id} row={row} onToggle={() => s.toggle(row.id)} />)}
      </ul>

      <div className="flex flex-col gap-3 px-5 py-4 border-t">
        {running ? (
          <div className="flex items-center gap-3" aria-live="polite">
            <span className="text-sm text-muted-foreground">Generating</span>
            <div className="flex-1"><ProgressLine done={running.cached_blocks} total={running.total_blocks} /></div>
            <span className="text-sm font-mono tabular-nums text-muted-foreground">{numberFormat.format(running.cached_blocks)} of {numberFormat.format(running.total_blocks)}</span>
            <Button variant="ghost" size="sm" onClick={() => void props.onCancel()}><Square />Stop</Button>
          </div>
        ) : (
          <span className="text-sm text-muted-foreground" aria-live="polite"><SelectionMeta s={s} /></span>
        )}
        <SelectionNotes s={s} />
        <div className="flex flex-wrap justify-end gap-2">
          {!s.allMade && !running && (
            <Button className="shadow-none" onClick={() => void s.start()} disabled={!s.canStart}>
              {s.isStarting && <Loader2 className="animate-spin" />}
              Generate
            </Button>
          )}
          <FormatsHint>
            <div className="flex gap-2">
              {EXPORT_FORMATS.map(format => {
                const building = props.exportProgress[format]?.building === true;
                const name = format.toUpperCase();
                return (
                  <Button
                    key={format}
                    variant={s.allMade ? "default" : "outline"}
                    className="shadow-none"
                    onClick={() => s.download(format)}
                    disabled={!s.allMade || building}
                  >
                    {building ? <Loader2 className="animate-spin" /> : <Download />}
                    {building ? `Building ${name}` : `Save ${name}`}
                  </Button>
                );
              })}
            </div>
          </FormatsHint>
        </div>
      </div>
    </>
  );
}

function SectionRow({ row, onToggle }: { row: RowState; onToggle: () => void }) {
  const made = row.blocksToMake === 0;
  const inProgress = row.inJob && row.blocksToMake !== null && !made;
  const madeBlocks = row.blocks - (row.blocksToMake ?? row.blocks);
  return (
    <li>
      <label className="flex items-start gap-3 rounded-md px-2 py-2 cursor-pointer hover:bg-accent/50 has-[:focus-visible]:outline-2 has-[:focus-visible]:-outline-offset-2 has-[:focus-visible]:outline-primary">
        <Tick checked={row.ticked} onChange={onToggle} />
        <span className="flex-1 min-w-0 flex flex-col gap-1.5">
          <span className={`leading-6 ${row.ticked ? "text-foreground" : "text-muted-foreground"}`}>{row.title}</span>
          {inProgress && <ProgressLine done={madeBlocks} total={row.blocks} />}
        </span>
        <span className="flex items-center gap-1.5 leading-6 text-sm text-muted-foreground font-mono tabular-nums shrink-0">
          {made && <><AudioLines className="h-3.5 w-3.5" aria-hidden /><span className="sr-only">Generated,</span></>}
          {inProgress ? `${madeBlocks}/${row.blocks}` : formatDuration(row.durationMs)}
        </span>
      </label>
    </li>
  );
}

/** A checkbox in the house's paint: a hairline box, filled with the accent and a ground-coloured tick when on. */
function Tick({ checked, onChange }: { checked: boolean; onChange: () => void }) {
  return (
    <span className="relative mt-1 size-4 shrink-0">
      <input
        type="checkbox"
        checked={checked}
        onChange={onChange}
        className="peer absolute inset-0 m-0 appearance-none rounded-[4px] border border-muted-foreground/50 bg-transparent cursor-pointer transition-colors checked:bg-primary checked:border-primary focus-visible:outline-none"
      />
      <Check strokeWidth={3} className="pointer-events-none absolute inset-0 m-auto size-3 text-primary-foreground opacity-0 peer-checked:opacity-100" />
    </span>
  );
}

/** One tooltip over both Save buttons, saying what each file is good for; it opens on hover and on keyboard focus. */
function FormatsHint({ children }: { children: React.ReactNode }) {
  return (
    <TooltipPrimitive.Provider delayDuration={500}>
      <TooltipPrimitive.Root>
        <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
        <TooltipPrimitive.Portal>
          <TooltipPrimitive.Content align="end" sideOffset={6} collisionPadding={8} className={`${overlayClass} flex flex-col gap-1.5`}>
            <p>Both hold the same audio, with a chapter for each section.</p>
            <p><span className="font-medium">M4B</span> is an audiobook: Apple Books and audiobook apps show its chapters and remember where you stopped.</p>
            <p><span className="font-medium">MP3</span> plays in any player on any device, though not every player shows its chapters.</p>
          </TooltipPrimitive.Content>
        </TooltipPrimitive.Portal>
      </TooltipPrimitive.Root>
    </TooltipPrimitive.Provider>
  );
}

/** A caution beside what it is about: a 2px bar and small muted text, never a filled box. */
function Note({ children }: { children: React.ReactNode }) {
  return <p className="border-l-2 border-accent-warning pl-3 text-sm text-muted-foreground">{children}</p>;
}

/** Every reason the ticked sections cannot be generated, or would be only in part, or failed to save, each as a note. */
function SelectionNotes({ s }: { s: AudioSelection }) {
  const { blocker, shortfall, refusal, exportErrors, totals } = s;
  return (
    <>
      {blocker?.kind === "browser-voice" && (
        <Note>
          A voice run on this device keeps its audio in this tab only.{" "}
          <button className={linkClass} onClick={s.useServerKokoro}>Run Kokoro on Cloud</button>
        </Note>
      )}
      {blocker?.kind === "running-elsewhere" && (
        <Note>
          You are generating audio for <Link className={linkClass} to={`/listen/${blocker.documentId}`}>another document</Link>. Stop it there or let it finish first.
        </Note>
      )}
      {blocker?.kind === "not-on-plan" && (
        <Note>
          {blocker.kokoro ? "Kokoro on Cloud is" : "This voice is"} not on your plan. <Link className={linkClass} to="/subscription">See plans</Link>
          {blocker.kokoro && ", or run Kokoro on this device to listen"}.
        </Note>
      )}
      {blocker?.kind === "no-characters" && (
        <Note>
          No characters are left on your plan this period. <Link className={linkClass} to="/subscription">See plans</Link>
        </Note>
      )}
      {shortfall !== null && (
        <Note>
          That needs {numberFormat.format(totals.charactersToSynthesize)} characters and your plan has {numberFormat.format(shortfall)} left, so generating stops partway.
        </Note>
      )}
      {refusal && <Note>{refusal}</Note>}
      {exportErrors.map(({ format, error }) => <Note key={format}>{error}</Note>)}
    </>
  );
}

/** The selection's length, and its characters only where the plan counts them. */
function SelectionMeta({ s }: { s: AudioSelection }) {
  const { totals, estimate, estimateFailed, onServer } = s;
  if (totals.blocks === 0) return <>Nothing ticked</>;
  const length = <span className="font-mono tabular-nums">{formatDuration(totals.durationMs)}</span>;
  if (estimateFailed) return <>{length} · could not check what is generated</>;
  if (!onServer || estimate === null) return length;
  const limit = estimate.available_characters;
  if (limit === null || s.blocker !== null || s.shortfall !== null || totals.charactersToSynthesize === 0) return length;
  return (
    <>
      {length} · <span className="font-mono tabular-nums">{numberFormat.format(totals.charactersToSynthesize)}</span> characters,{" "}
      <span className="font-mono tabular-nums">{numberFormat.format(limit)}</span> left
    </>
  );
}

/** An explanation one click away: an (i) that opens a short note under it. */
function InfoHint({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <PopoverPrimitive.Root>
      <PopoverPrimitive.Trigger aria-label={label} className="p-1 rounded text-muted-foreground hover:text-primary transition-colors">
        <Info className="h-4 w-4" />
      </PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content sideOffset={6} collisionPadding={8} className={overlayClass}>{children}</PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}

/** A thin progress line: a hairline track, filled in body ink. */
function ProgressLine({ done, total }: { done: number; total: number }) {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  return (
    <div className="h-0.5 w-full bg-border rounded-full overflow-hidden" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={done}>
      <div className="h-full bg-foreground/70 transition-[width] duration-150" style={{ width: `${pct}%` }} />
    </div>
  );
}

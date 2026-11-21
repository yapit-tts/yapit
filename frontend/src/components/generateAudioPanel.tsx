import { Check, Download, Loader2, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { VoicePicker } from "@/components/voicePicker";
import { InfoHint, ProgressLine, SelectionMeta, SelectionNotes, numberFormat } from "@/components/audioParts";
import { type AudioSelectionProps, type RowState, useAudioSelection } from "@/hooks/useAudioSelection";
import { EXPORT_FORMATS } from "@/lib/audioJob";
import { formatDuration } from "@/lib/sectionIndex";

interface GenerateAudioPanelProps extends AudioSelectionProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** Variant C: a panel at the right edge, like the outline; each section shows its own progress, and the actions sit at the foot. */
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
  const s = useAudioSelection(props, () => {});
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
        {s.rows.map(row => <PanelRow key={row.id} row={row} generating={running !== null} onToggle={() => s.toggle(row.id)} />)}
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
          <span className="text-sm text-muted-foreground font-mono tabular-nums" aria-live="polite"><SelectionMeta s={s} /></span>
        )}
        <SelectionNotes s={s} making="generating" />
        <div className="flex flex-wrap gap-2">
          {!s.allMade && !running && (
            <Button className="shadow-none basis-full sm:basis-auto" onClick={() => void s.start()} disabled={!s.canStart}>
              {s.isStarting && <Loader2 className="animate-spin" />}
              Generate
            </Button>
          )}
          {EXPORT_FORMATS.map(format => {
            const building = props.exportProgress[format]?.building === true;
            return (
              <Button
                key={format}
                variant={s.allMade ? "default" : "outline"}
                className="shadow-none"
                title={format === "m4b" ? "An audiobook file with chapters, for Apple Books and most audiobook players" : "Plays everywhere; chapters show in some players"}
                onClick={() => s.download(format)}
                disabled={!s.allMade || building}
              >
                {building ? <Loader2 className="animate-spin" /> : <Download />}
                Save {format.toUpperCase()}
              </Button>
            );
          })}
        </div>
      </div>
    </>
  );
}

function PanelRow({ row, generating, onToggle }: { row: RowState; generating: boolean; onToggle: () => void }) {
  const made = row.blocksToMake === 0;
  const inProgress = generating && row.ticked && row.blocksToMake !== null && !made;
  const madeBlocks = row.blocks - (row.blocksToMake ?? row.blocks);
  return (
    <li>
      <label className="flex items-start gap-3 rounded-md px-2 py-2 cursor-pointer hover:bg-accent has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-primary">
        <input type="checkbox" checked={row.ticked} onChange={onToggle} className="h-4 w-4 mt-1 shrink-0 accent-primary focus-visible:outline-none" />
        <span className="flex-1 min-w-0 flex flex-col gap-1.5">
          <span className={`leading-6 ${row.ticked ? "text-foreground" : "text-muted-foreground"}`}>{row.title}</span>
          {inProgress && <ProgressLine done={madeBlocks} total={row.blocks} />}
        </span>
        <span className="flex items-center gap-1.5 leading-6 text-sm text-muted-foreground font-mono tabular-nums shrink-0">
          {made && <Check className="h-3.5 w-3.5" aria-label="Generated" />}
          {inProgress ? `${madeBlocks}/${row.blocks}` : formatDuration(row.durationMs)}
        </span>
      </label>
    </li>
  );
}

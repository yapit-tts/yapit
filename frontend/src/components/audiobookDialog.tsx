import { Check, Download, Loader2, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { VoicePicker } from "@/components/voicePicker";
import { InfoHint, ProgressLine, SelectionMeta, SelectionNotes, numberFormat } from "@/components/audioParts";
import { type AudioSelectionProps, type RowState, useAudioSelection } from "@/hooks/useAudioSelection";
import { EXPORT_FORMATS } from "@/lib/audioJob";
import { formatDuration } from "@/lib/sectionIndex";

interface AudiobookDialogProps extends AudioSelectionProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** Variant A: a modal over the reader, the sections as a list of chapters, the next step as the one solid button. */
export function AudiobookDialog(props: AudiobookDialogProps) {
  return (
    <Dialog open={props.open} onOpenChange={props.onOpenChange}>
      <DialogContent className="sm:max-w-lg max-h-[calc(100dvh-2rem)] flex flex-col gap-5 shadow-none">
        {props.open && <AudiobookForm {...props} />}
      </DialogContent>
    </Dialog>
  );
}

function AudiobookForm(props: AudiobookDialogProps) {
  const s = useAudioSelection(props, () => props.onOpenChange(false));
  const { job } = props;
  const running = s.jobRunsHere && job ? job : null;

  return (
    <>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 pr-8">
        <div className="flex items-center gap-1">
          <DialogTitle className="text-xl font-semibold text-foreground">Audiobook</DialogTitle>
          <InfoHint label="What an audiobook is">
            The ticked sections, read in the voice you pick, as one file with a chapter per section. They are made on the server, carry on with this tab closed, and play back without waiting.
          </InfoHint>
        </div>
        <DialogDescription className="sr-only">Pick the sections and the voice, make their audio, then download it as one file.</DialogDescription>
        <div className="sm:ml-auto"><VoicePicker value={props.voiceSelection} onChange={props.onVoiceChange} /></div>
      </div>

      <ul aria-label="Sections" className="overflow-y-auto min-h-0 max-h-[45dvh] -mx-2 px-2">
        {s.rows.map(row => <ChapterRow key={row.id} row={row} onToggle={() => s.toggle(row.id)} />)}
      </ul>

      <div className="flex flex-col gap-3">
        {running ? (
          <div className="flex items-center gap-3" aria-live="polite">
            <div className="flex-1 flex flex-col gap-1.5">
              <span className="text-sm text-muted-foreground">
                Making <span className="font-mono tabular-nums">{numberFormat.format(running.cached_blocks)} of {numberFormat.format(running.total_blocks)}</span> blocks
              </span>
              <ProgressLine done={running.cached_blocks} total={running.total_blocks} />
            </div>
            <Button variant="ghost" size="sm" onClick={() => void props.onCancel()}><Square />Stop</Button>
          </div>
        ) : (
          <span className="text-sm text-muted-foreground font-mono tabular-nums" aria-live="polite">
            <SelectionMeta s={s} />
          </span>
        )}
        <SelectionNotes s={s} making="making" />
      </div>

      <div className="flex flex-wrap items-center gap-2">
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
              {format.toUpperCase()}
            </Button>
          );
        })}
        {!s.allMade && !running && (
          <Button className="ml-auto shadow-none" onClick={() => void s.start()} disabled={!s.canStart}>
            {s.isStarting && <Loader2 className="animate-spin" />}
            Make audiobook
          </Button>
        )}
      </div>
    </>
  );
}

function ChapterRow({ row, onToggle }: { row: RowState; onToggle: () => void }) {
  const made = row.blocksToMake === 0;
  return (
    <li>
      <label className="flex items-center gap-3 rounded-md px-2 -mx-2 min-h-10 cursor-pointer hover:bg-accent has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-primary">
        <input type="checkbox" checked={row.ticked} onChange={onToggle} className="h-4 w-4 shrink-0 accent-primary focus-visible:outline-none" />
        <span className={`flex-1 min-w-0 py-2 leading-snug ${row.ticked ? "text-foreground" : "text-muted-foreground"}`}>{row.title}</span>
        {made && <Check className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-label="Made" />}
        <span className="w-10 text-right text-sm text-muted-foreground font-mono tabular-nums shrink-0">{formatDuration(row.durationMs)}</span>
      </label>
    </li>
  );
}

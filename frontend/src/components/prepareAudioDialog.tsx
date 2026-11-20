import { useEffect, useState } from "react";
import { Link } from "react-router";
import { AlertTriangle, Info, Loader2 } from "lucide-react";
import { useApi } from "@/api";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { VoicePicker } from "@/components/voicePicker";
import {
  type AudioJob,
  type AudioJobEstimate,
  type BlockRange,
  type ExportRow,
  exportRows,
  exportTotals,
} from "@/lib/audioJob";
import { formatDuration, type Section } from "@/lib/sectionIndex";
import { KOKORO_SLUG, isKokoroModel, isServerSideModel, setVoiceSelection, type VoiceSelection } from "@/lib/voiceSelection";

interface PrepareAudioDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  documentId: string;
  sections: Section[];
  documentBlocks: { est_duration_ms: number }[];
  expandedSections: Set<string>;
  voiceSelection: VoiceSelection;
  onVoiceChange: (selection: VoiceSelection) => void;
  job: AudioJob | null;
  onStart: (model: string, voice: string, ranges: BlockRange[]) => Promise<string | null>;
}

export function PrepareAudioDialog(props: PrepareAudioDialogProps) {
  return (
    <Dialog open={props.open} onOpenChange={props.onOpenChange}>
      <DialogContent className="sm:max-w-lg max-h-[calc(100dvh-2rem)] flex flex-col">
        {props.open && <PrepareAudioForm {...props} />}
      </DialogContent>
    </Dialog>
  );
}

const numberFormat = new Intl.NumberFormat();

function PrepareAudioForm({
  onOpenChange,
  documentId,
  sections,
  documentBlocks,
  expandedSections,
  voiceSelection,
  onVoiceChange,
  job,
  onStart,
}: PrepareAudioDialogProps) {
  const { api } = useApi();
  const rows = exportRows(sections, documentBlocks, expandedSections);
  const [ticked, setTicked] = useState<Set<string>>(() => new Set(rows.filter(r => r.initiallyTicked).map(r => r.id)));
  const [fetched, setFetched] = useState<{ key: string; estimate: AudioJobEstimate | null } | null>(null);
  const [isStarting, setIsStarting] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);

  const onServer = isServerSideModel(voiceSelection.model);
  const { model, voiceSlug } = voiceSelection;
  const jobRunsHere = job?.status === "running";
  // A started or stopped job changes what is running, so the estimate is asked for again.
  const estimateKey = `${model}:${voiceSlug}:${jobRunsHere}`;
  const estimate = fetched?.key === estimateKey ? fetched.estimate : null;
  const estimateFailed = fetched?.key === estimateKey && fetched.estimate === null;

  useEffect(() => {
    if (!onServer) return;
    let stale = false;
    api.get<AudioJobEstimate>(`/v1/documents/${documentId}/audio-job/estimate`, { params: { model, voice: voiceSlug } })
      .then(({ data }) => { if (!stale) setFetched({ key: estimateKey, estimate: data }); })
      .catch(err => { console.error("Failed to estimate audio job:", err); if (!stale) setFetched({ key: estimateKey, estimate: null }); });
    return () => { stale = true; };
  }, [api, documentId, onServer, model, voiceSlug, estimateKey]);

  const tickedRows = rows.filter(r => ticked.has(r.id));
  const totals = exportTotals(tickedRows, estimate?.uncached_characters ?? null);
  const blocker = onServer ? jobBlocker(estimate, totals, model, documentId) : null;
  const shortfall = onServer && blocker === null ? jobShortfall(estimate, totals) : null;
  const canPrepare = onServer && estimate !== null && blocker === null && !jobRunsHere && totals.blocksToSynthesize > 0 && !isStarting;

  const toggle = (id: string) => setTicked(prev => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  const switchToServerKokoro = () => {
    const selection = { model: KOKORO_SLUG, voiceSlug };
    onVoiceChange(selection);
    setVoiceSelection(selection);
  };

  const prepare = async () => {
    setIsStarting(true);
    setRefusal(null);
    const ranges = tickedRows.map(r => ({ first_block: r.firstBlock, last_block: r.lastBlock, title: r.title.slice(0, 500) }));
    const reason = await onStart(model, voiceSlug, ranges);
    setIsStarting(false);
    if (reason) setRefusal(reason);
    else onOpenChange(false);
  };

  return (
    <>
      <DialogHeader>
        <DialogTitle>Prepare audio</DialogTitle>
        <DialogDescription>
          Synthesize the sections you pick on the server, so playback never waits. It keeps going with this tab closed.
        </DialogDescription>
      </DialogHeader>

      <div className="flex items-center justify-between gap-3">
        <span className="text-sm font-medium">Voice</span>
        <VoicePicker value={voiceSelection} onChange={onVoiceChange} />
      </div>

      <div role="group" aria-labelledby="prepare-audio-sections" className="flex flex-col min-h-0 min-w-0 gap-2">
        <div className="flex items-center justify-between">
          <span id="prepare-audio-sections" className="text-sm font-medium">Sections</span>
        </div>
        <div className="overflow-y-auto min-h-0 max-h-[40dvh] -mx-2 px-2">
          {rows.map(row => (
            <SectionRow key={row.id} row={row} ticked={ticked.has(row.id)} onToggle={() => toggle(row.id)} />
          ))}
        </div>
      </div>

      <div className="text-sm text-muted-foreground tabular-nums" aria-live="polite">
        {!onServer ? null
          : estimateFailed ? <span className="text-destructive">Could not check what is already prepared.</span>
          : estimate === null ? <span className="flex items-center gap-2"><Loader2 className="h-3.5 w-3.5 animate-spin" />Checking what is already prepared…</span>
          : <TotalsLine totals={totals} estimate={estimate} model={model} />}
      </div>

      {!onServer && (
        <Notice>
          Kokoro in your browser keeps its audio in this tab only. Prepared audio is made on the server.{" "}
          <button className="font-medium text-primary hover:underline" onClick={switchToServerKokoro}>Use server Kokoro</button>
        </Notice>
      )}
      {blocker && <Notice tone="warning">{blocker}</Notice>}
      {shortfall && <Notice tone="warning">{shortfall}</Notice>}
      {refusal && <Notice tone="warning">{refusal}</Notice>}
      {jobRunsHere && !blocker && (
        <Notice>Audio is being prepared for this document. Its progress, and its Stop button, are on the playback bar.</Notice>
      )}

      <DialogFooter>
        <Button onClick={() => void prepare()} disabled={!canPrepare}>
          {isStarting && <Loader2 className="animate-spin" />}
          Prepare audio
        </Button>
      </DialogFooter>
    </>
  );
}

function SectionRow({ row, ticked, onToggle }: { row: ExportRow; ticked: boolean; onToggle: () => void }) {
  return (
    <label className="flex items-center gap-3 rounded-md px-2 -mx-2 py-2 min-h-11 cursor-pointer hover:bg-muted/60 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring/50">
      <input
        type="checkbox"
        checked={ticked}
        onChange={onToggle}
        className="h-4 w-4 shrink-0 accent-primary focus-visible:outline-none"
      />
      <span className={`flex-1 min-w-0 truncate text-sm ${ticked ? "" : "text-muted-foreground"}`}>{row.title}</span>
      <span className="text-sm text-muted-foreground tabular-nums shrink-0">{formatDuration(row.durationMs)}</span>
    </label>
  );
}

function TotalsLine({ totals, estimate, model }: { totals: ReturnType<typeof exportTotals>; estimate: AudioJobEstimate; model: string }) {
  if (totals.blocks === 0) return <>Tick the sections to prepare.</>;
  const cached = totals.blocks - totals.blocksToSynthesize;
  const parts = [formatDuration(totals.durationMs)];
  if (totals.blocksToSynthesize === 0) parts.push("all of it is prepared already");
  else {
    parts.push(`${numberFormat.format(totals.charactersToSynthesize)} characters to synthesize`);
    if (cached > 0) parts.push(`${numberFormat.format(cached)} of ${numberFormat.format(totals.blocks)} blocks prepared already`);
  }
  const quota = estimate.available_characters === null
    ? `${isKokoroModel(model) ? "server Kokoro" : "this voice"} is unlimited on your plan`
    : `${numberFormat.format(estimate.available_characters)} characters left on your plan`;
  return <>{parts.join(" · ")}<br />{quota}</>;
}

/** Why a job over these totals cannot start, or would stop short; null where nothing stands in its way. */
function jobBlocker(estimate: AudioJobEstimate | null, totals: ReturnType<typeof exportTotals>, model: string, documentId: string): React.ReactNode {
  if (!estimate) return null;
  const running = estimate.running_job_document_id;
  if (running === documentId) return null;
  if (running) {
    return <>You are already preparing audio for <Link className="font-medium text-primary hover:underline" to={`/listen/${running}`}>another document</Link>. Stop it there, or wait until it is done.</>;
  }
  if (totals.blocksToSynthesize === 0) return null;
  const available = estimate.available_characters;
  if (available === 0) {
    return isKokoroModel(model)
      ? <>Server Kokoro is not on your plan. <Link className="font-medium text-primary hover:underline" to="/subscription">See plans</Link>, or listen with Kokoro in your browser.</>
      : <>You have no characters left for this voice this period. <Link className="font-medium text-primary hover:underline" to="/subscription">See plans</Link>.</>;
  }
  if (estimate.daily_blocks_left !== null && estimate.daily_blocks_left <= 0) {
    return <>You have prepared as much audio as one day allows. Try again tomorrow (the limit resets at midnight UTC).</>;
  }
  return null;
}

/** Why a job over these totals would stop before it is done; null where it can finish. */
function jobShortfall(estimate: AudioJobEstimate | null, totals: ReturnType<typeof exportTotals>): string | null {
  if (!estimate || totals.blocksToSynthesize === 0) return null;
  const available = estimate.available_characters;
  if (available !== null && available < totals.charactersToSynthesize) {
    return `That is more than the ${numberFormat.format(available)} characters left on your plan, so preparing stops when they run out.`;
  }
  const dailyLeft = estimate.daily_blocks_left;
  if (dailyLeft !== null && dailyLeft < totals.blocksToSynthesize) {
    return `Today's limit covers ${numberFormat.format(dailyLeft)} more blocks, so preparing stops there. Start it again tomorrow for the rest.`;
  }
  return null;
}

function Notice({ children, tone = "info" }: { children: React.ReactNode; tone?: "info" | "warning" }) {
  const Icon = tone === "warning" ? AlertTriangle : Info;
  return (
    <div className={`flex items-start gap-2.5 rounded-lg border px-3 py-2.5 text-sm ${tone === "warning" ? "border-destructive/30 bg-destructive/10" : "border-border bg-muted/50"}`}>
      <Icon className={`h-4 w-4 shrink-0 mt-0.5 ${tone === "warning" ? "text-destructive" : "text-muted-foreground"}`} />
      <p className="text-foreground">{children}</p>
    </div>
  );
}

import { useEffect, useState } from "react";
import { useApi } from "@/api";
import {
  type AudioJob,
  type AudioJobEstimate,
  type BlockRange,
  EXPORT_FORMATS,
  type ExportFormat,
  type ExportRow,
  type ExportTotals,
  MAX_RANGE_TITLE,
  exportRows,
  exportTotals,
} from "@/lib/audioJob";
import type { ExportProgress } from "@/hooks/useAudioExport";
import type { Section } from "@/lib/sectionIndex";
import { KOKORO_SLUG, isKokoroModel, isServerSideModel, setVoiceSelection, type VoiceSelection } from "@/lib/voiceSelection";

export interface AudioSelectionProps {
  documentId: string;
  sections: Section[];
  documentBlocks: { est_duration_ms: number }[];
  expandedSections: Set<string>;
  voiceSelection: VoiceSelection;
  onVoiceChange: (selection: VoiceSelection) => void;
  job: AudioJob | null;
  onStart: (model: string, voice: string, ranges: BlockRange[]) => Promise<string | null>;
  onCancel: () => Promise<void>;
  exportProgress: ExportProgress;
  onDownload: (format: ExportFormat, model: string, voice: string, ranges: BlockRange[]) => Promise<void>;
}

/** What stops a job over the ticked sections from starting. */
export type Blocker =
  | { kind: "browser-voice" }
  | { kind: "running-elsewhere"; documentId: string }
  | { kind: "not-on-plan"; kokoro: boolean }
  | { kind: "no-characters" };

export interface RowState extends ExportRow {
  ticked: boolean;
  blocks: number;
  /** Blocks of the row whose audio is not made yet in the chosen voice; null until the estimate arrives. */
  blocksToMake: number | null;
  /** Whether this document's running job, in the chosen voice, covers any of the row's blocks. */
  inJob: boolean;
}

/** The ticked sections, what generating their audio costs, and what stands in its way: the state the Generate in background panel renders. */
export function useAudioSelection(props: AudioSelectionProps) {
  const { documentId, sections, documentBlocks, expandedSections, voiceSelection, onVoiceChange, job, onStart, exportProgress, onDownload } = props;
  const { api } = useApi();
  const [baseRows] = useState(() => exportRows(sections, documentBlocks, expandedSections));
  const [ticked, setTicked] = useState<Set<string>>(() => new Set(baseRows.filter(r => r.initiallyTicked).map(r => r.id)));
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

  // While this document's job runs in the chosen voice, a block it has made since the estimate counts as made.
  const madeByJob = new Set<number>();
  const coveredByJob = new Set<number>();
  if (jobRunsHere && job.model === model && job.voice === voiceSlug) {
    const pending = new Set(job.pending_blocks);
    for (const r of job.ranges) {
      for (let idx = r.first_block; idx <= r.last_block; idx++) {
        coveredByJob.add(idx);
        if (!pending.has(idx)) madeByJob.add(idx);
      }
    }
  }
  const toMake = (idx: number) => (estimate?.uncached_characters[idx] ?? 0) > 0 && !madeByJob.has(idx);

  const rows: RowState[] = baseRows.map(r => {
    let blocksToMake = 0;
    let inJob = false;
    for (let idx = r.firstBlock; idx <= r.lastBlock; idx++) {
      if (toMake(idx)) blocksToMake++;
      if (coveredByJob.has(idx)) inJob = true;
    }
    return { ...r, ticked: ticked.has(r.id), blocks: r.lastBlock - r.firstBlock + 1, blocksToMake: estimate ? blocksToMake : null, inJob };
  });
  const tickedRows = rows.filter(r => r.ticked);
  const totals: ExportTotals = exportTotals(tickedRows, estimate?.uncached_characters ?? null);

  const blocker: Blocker | null = !onServer ? { kind: "browser-voice" } : findBlocker(estimate, totals, documentId, model);
  const shortfall = blocker === null && estimate?.available_characters != null && totals.blocksToSynthesize > 0
    && estimate.available_characters < totals.charactersToSynthesize ? estimate.available_characters : null;
  const canStart = onServer && estimate !== null && blocker === null && !jobRunsHere && totals.blocksToSynthesize > 0 && !isStarting;
  const allMade = onServer && estimate !== null && totals.blocks > 0 && totals.blocksToSynthesize === 0;
  const exportErrors = EXPORT_FORMATS.flatMap(format => {
    const progress = exportProgress[format];
    return progress?.phase === "failed" ? [{ format, error: progress.error }] : [];
  });
  const saving = EXPORT_FORMATS.flatMap(format => {
    const progress = exportProgress[format];
    return progress && progress.phase !== "failed" ? [{ format, ...progress }] : [];
  });

  const toggle = (id: string) => setTicked(prev => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const setAll = (on: boolean) => setTicked(on ? new Set(rows.map(r => r.id)) : new Set());

  const useServerKokoro = () => {
    const selection = { model: KOKORO_SLUG, voiceSlug };
    onVoiceChange(selection);
    setVoiceSelection(selection);
  };

  const tickedRanges = () => tickedRows.map(r => ({ first_block: r.firstBlock, last_block: r.lastBlock, title: r.title.slice(0, MAX_RANGE_TITLE) }));

  const start = async () => {
    setIsStarting(true);
    setRefusal(null);
    const reason = await onStart(model, voiceSlug, tickedRanges());
    setIsStarting(false);
    if (reason) setRefusal(reason);
  };

  const download = (format: ExportFormat) => void onDownload(format, model, voiceSlug, tickedRanges());

  return {
    rows, toggle, setAll, totals, estimate, estimateFailed, onServer, jobRunsHere, isStarting,
    blocker, shortfall, refusal, canStart, allMade, exportErrors, saving, useServerKokoro, start, download,
  };
}

export type AudioSelection = ReturnType<typeof useAudioSelection>;

function findBlocker(estimate: AudioJobEstimate | null, totals: ExportTotals, documentId: string, model: string): Blocker | null {
  if (!estimate) return null;
  const running = estimate.running_job_document_id;
  if (running === documentId) return null;
  if (running) return { kind: "running-elsewhere", documentId: running };
  if (totals.blocksToSynthesize === 0) return null;
  if (!estimate.plan_includes_voice) return { kind: "not-on-plan", kokoro: isKokoroModel(model) };
  if (estimate.available_characters === 0) return { kind: "no-characters" };
  return null;
}

// Background audio jobs: the dialog's sections and totals, and the API's shapes.

import type { Section } from "./sectionIndex";

export type AudioJobStatus = "running" | "done" | "cancelled" | "usage_limit" | "daily_limit" | "failed";

export interface BlockRange {
  first_block: number;
  last_block: number; // inclusive
  title: string;
}

export interface AudioJob {
  document_id: string;
  model: string;
  voice: string;
  ranges: BlockRange[];
  status: AudioJobStatus;
  error: string | null;
  total_blocks: number;
  cached_blocks: number;
  pending_blocks: number[];
}

export interface AudioJobEstimate {
  uncached_characters: number[]; // per audio block; 0 where cached
  available_characters: number | null; // null: unlimited
  daily_blocks_left: number | null; // null: no daily ceiling applies
  running_job_document_id: string | null;
}

export interface ExportRow {
  id: string;
  title: string;
  firstBlock: number;
  lastBlock: number;
  durationMs: number;
  /** Ticked when the dialog opens: the outliner's expanded sections, and always the blocks before the first heading. */
  initiallyTicked: boolean;
}

export const PRELUDE_ROW_ID = "__before_first_heading";

/** The dialog's rows: the outliner's sections, with a row for the blocks before the first heading, or one row for a document without headings. */
export function exportRows(
  sections: Section[],
  blocks: { est_duration_ms: number }[],
  expandedSections: Set<string>,
): ExportRow[] {
  if (blocks.length === 0) return [];
  const duration = (first: number, last: number) =>
    blocks.slice(first, last + 1).reduce((sum, b) => sum + (b.est_duration_ms || 0), 0);

  if (sections.length === 0) {
    const last = blocks.length - 1;
    return [{ id: PRELUDE_ROW_ID, title: "Whole document", firstBlock: 0, lastBlock: last, durationMs: duration(0, last), initiallyTicked: true }];
  }

  const rows: ExportRow[] = sections.map(s => ({
    id: s.id,
    title: s.title || "Untitled section",
    firstBlock: s.startBlockIdx,
    lastBlock: s.endBlockIdx,
    durationMs: s.durationMs,
    initiallyTicked: expandedSections.has(s.id),
  }));
  const firstHeading = sections[0].startBlockIdx;
  if (firstHeading > 0) {
    rows.unshift({
      id: PRELUDE_ROW_ID,
      title: "Before the first heading",
      firstBlock: 0,
      lastBlock: firstHeading - 1,
      durationMs: duration(0, firstHeading - 1),
      initiallyTicked: true,
    });
  }
  return rows;
}

export interface ExportTotals {
  durationMs: number;
  blocks: number;
  /** Blocks whose audio is not cached in the chosen voice. */
  blocksToSynthesize: number;
  charactersToSynthesize: number;
}

export function exportTotals(rows: ExportRow[], uncachedCharacters: number[] | null): ExportTotals {
  const totals: ExportTotals = { durationMs: 0, blocks: 0, blocksToSynthesize: 0, charactersToSynthesize: 0 };
  for (const row of rows) {
    totals.durationMs += row.durationMs;
    totals.blocks += row.lastBlock - row.firstBlock + 1;
    if (!uncachedCharacters) continue;
    for (let idx = row.firstBlock; idx <= row.lastBlock; idx++) {
      const characters = uncachedCharacters[idx] ?? 0;
      if (characters > 0) {
        totals.blocksToSynthesize++;
        totals.charactersToSynthesize += characters;
      }
    }
  }
  return totals;
}

import { describe, it, expect } from "vitest";
import { exportRows, exportTotals, PRELUDE_ROW_ID } from "./audioJob";
import { buildSectionIndex } from "./sectionIndex";
import type { StructuredDocument } from "@/components/structuredDocument";

function heading(id: string, audioIdx: number) {
  return { type: "heading", id, level: 1, ast: [{ type: "text", content: id }], audio_chunks: [{ text: id, audio_block_idx: audioIdx }] };
}

function paragraph(id: string, audioIdx: number) {
  return { type: "paragraph", id, ast: [{ type: "text", content: "text" }], audio_chunks: [{ text: "text", audio_block_idx: audioIdx }] };
}

// Blocks 0-1 come before the first heading; "Methods" is collapsed in the outliner.
const doc = {
  version: "1",
  blocks: [
    paragraph("p0", 0), paragraph("p1", 1),
    heading("Introduction", 2), paragraph("p3", 3),
    heading("Methods", 4), paragraph("p5", 5), paragraph("p6", 6),
  ],
} as unknown as StructuredDocument;
const blocks = [1000, 2000, 3000, 4000, 5000, 6000, 7000].map(ms => ({ est_duration_ms: ms }));
const sections = buildSectionIndex(doc, blocks);

describe("exportRows", () => {
  const rows = exportRows(sections, blocks, new Set(["Introduction"]));

  it("adds a row for the blocks before the first heading, ticked", () => {
    expect(rows[0]).toMatchObject({ id: PRELUDE_ROW_ID, firstBlock: 0, lastBlock: 1, durationMs: 3000, initiallyTicked: true });
  });

  it("ticks the outliner's expanded sections and leaves its collapsed ones unticked", () => {
    expect(rows.slice(1).map(r => [r.title, r.firstBlock, r.lastBlock, r.initiallyTicked])).toEqual([
      ["Introduction", 2, 3, true],
      ["Methods", 4, 6, false],
    ]);
  });

  it("adds no prelude row to a document that opens with a heading", () => {
    const opensWithHeading = {
      version: "1",
      blocks: [heading("Introduction", 0), paragraph("p1", 1), heading("Methods", 2)],
    } as unknown as StructuredDocument;
    const threeBlocks = blocks.slice(0, 3);

    const titles = exportRows(buildSectionIndex(opensWithHeading, threeBlocks), threeBlocks, new Set()).map(r => r.title);

    expect(titles).toEqual(["Introduction", "Methods"]);
  });

  it("gives a document without headings one row over every block", () => {
    expect(exportRows([], blocks, new Set())).toMatchObject([{ firstBlock: 0, lastBlock: 6, durationMs: 28000 }]);
  });
});

describe("exportTotals", () => {
  it("counts the characters of the ticked rows' uncached blocks only", () => {
    const rows = exportRows(sections, blocks, new Set());
    const uncached = [10, 0, 30, 40, 0, 0, 70];

    const totals = exportTotals([rows[0], rows[2]], uncached);

    expect(totals).toEqual({ durationMs: 3000 + 18000, blocks: 5, blocksToSynthesize: 2, charactersToSynthesize: 80 });
  });

  it("counts duration and blocks while the estimate is still on its way", () => {
    const rows = exportRows(sections, blocks, new Set());

    expect(exportTotals(rows, null)).toEqual({ durationMs: 28000, blocks: 7, blocksToSynthesize: 0, charactersToSynthesize: 0 });
  });
});

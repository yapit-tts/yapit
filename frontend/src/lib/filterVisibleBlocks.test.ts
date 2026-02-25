import { describe, it, expect } from "vitest";
import { filterVisibleBlocks } from "./filterVisibleBlocks";
import type { ContentBlock } from "@/components/structuredDocument";
import type { Section } from "@/lib/sectionIndex";

// --- Helpers ---

function makeHeading(
  id: string,
  audioIdx: number,
  level: 1 | 2 = 1,
): ContentBlock {
  return {
    type: "heading",
    id,
    level,
    html: id,
    ast: [{ type: "text", content: id }],
    audio_chunks: [{ text: id, audio_block_idx: audioIdx }],
  } as ContentBlock;
}

function makeParagraph(id: string, audioIdx: number): ContentBlock {
  return {
    type: "paragraph",
    id,
    html: "text",
    ast: [{ type: "text", content: "text" }],
    audio_chunks: [{ text: "text", audio_block_idx: audioIdx }],
  } as ContentBlock;
}

function makeDisplayOnly(id: string, type: string = "paragraph"): ContentBlock {
  return {
    type,
    id,
    html: "display-only",
    ast: [{ type: "text", content: "display-only" }],
    audio_chunks: [],
  } as ContentBlock;
}

function makeSection(
  id: string,
  start: number,
  end: number,
): Section {
  return {
    id,
    title: id,
    level: 1,
    startBlockIdx: start,
    endBlockIdx: end,
    durationMs: 1000,
    subsections: [],
  };
}

// --- Tests ---

describe("filterVisibleBlocks", () => {
  it("passes through all blocks when no sections exist", () => {
    const blocks = [makeParagraph("p1", 0), makeParagraph("p2", 1)];
    const result = filterVisibleBlocks(blocks, [], new Set(), new Map());
    // No sections = no outliner = no filtering
    expect(result).toEqual(blocks);
  });

  it("shows blocks in expanded sections", () => {
    const h1 = makeHeading("h1", 0);
    const p1 = makeParagraph("p1", 1);
    const blocks = [h1, p1];
    const sections = [makeSection("h1", 0, 1)];
    const sectionMap = new Map([["h1", sections[0]]]);

    const result = filterVisibleBlocks(blocks, sections, new Set(["h1"]), sectionMap);
    expect(result).toEqual([h1, p1]);
  });

  it("hides content but keeps heading when section is collapsed", () => {
    const h1 = makeHeading("h1", 0);
    const p1 = makeParagraph("p1", 1);
    const blocks = [h1, p1];
    const sections = [makeSection("h1", 0, 1)];
    const sectionMap = new Map([["h1", sections[0]]]);

    const result = filterVisibleBlocks(blocks, sections, new Set(), sectionMap);
    expect(result).toEqual([h1]);
  });

  it("shows audio blocks before the first heading (preamble)", () => {
    const p0 = makeParagraph("p0", 0);
    const p1 = makeParagraph("p1", 1);
    const h1 = makeHeading("h1", 2);
    const p2 = makeParagraph("p2", 3);
    const blocks = [p0, p1, h1, p2];
    const sections = [makeSection("h1", 2, 3)];
    const sectionMap = new Map([["h1", sections[0]]]);

    const result = filterVisibleBlocks(blocks, sections, new Set(["h1"]), sectionMap);
    expect(result).toEqual([p0, p1, h1, p2]);
  });

  it("shows display-only blocks before the first heading", () => {
    const copyright = makeDisplayOnly("copyright");
    const h1 = makeHeading("h1", 0);
    const p1 = makeParagraph("p1", 1);
    const blocks = [copyright, h1, p1];
    const sections = [makeSection("h1", 0, 1)];
    const sectionMap = new Map([["h1", sections[0]]]);

    const result = filterVisibleBlocks(blocks, sections, new Set(["h1"]), sectionMap);
    expect(result).toEqual([copyright, h1, p1]);
  });

  it("shows multiple display-only blocks before first heading", () => {
    const notice1 = makeDisplayOnly("notice1");
    const notice2 = makeDisplayOnly("notice2");
    const h1 = makeHeading("h1", 0);
    const blocks = [notice1, notice2, h1];
    const sections = [makeSection("h1", 0, 0)];
    const sectionMap = new Map([["h1", sections[0]]]);

    const result = filterVisibleBlocks(blocks, sections, new Set(["h1"]), sectionMap);
    expect(result).toEqual([notice1, notice2, h1]);
  });

  it("shows display-only blocks in expanded sections", () => {
    const h1 = makeHeading("h1", 0);
    const code = makeDisplayOnly("code1", "code");
    const p1 = makeParagraph("p1", 1);
    const blocks = [h1, code, p1];
    const sections = [makeSection("h1", 0, 1)];
    const sectionMap = new Map([["h1", sections[0]]]);

    const result = filterVisibleBlocks(blocks, sections, new Set(["h1"]), sectionMap);
    expect(result).toEqual([h1, code, p1]);
  });

  it("hides display-only blocks in collapsed sections", () => {
    const h1 = makeHeading("h1", 0);
    const code = makeDisplayOnly("code1", "code");
    const p1 = makeParagraph("p1", 1);
    const blocks = [h1, code, p1];
    const sections = [makeSection("h1", 0, 1)];
    const sectionMap = new Map([["h1", sections[0]]]);

    const result = filterVisibleBlocks(blocks, sections, new Set(), sectionMap);
    expect(result).toEqual([h1]);
  });

  it("handles mixed sections with display-only blocks", () => {
    const copyright = makeDisplayOnly("copyright");
    const h1 = makeHeading("h1", 0);
    const p1 = makeParagraph("p1", 1);
    const h2 = makeHeading("h2", 2, 2);
    const table = makeDisplayOnly("table1", "table");
    const p2 = makeParagraph("p2", 3);
    const blocks = [copyright, h1, p1, h2, table, p2];
    const sec1 = makeSection("h1", 0, 1);
    const sec2 = makeSection("h2", 2, 3);
    const sections = [sec1, sec2];
    const sectionMap = new Map([
      ["h1", sec1],
      ["h2", sec2],
    ]);

    // h1 expanded, h2 collapsed
    const result = filterVisibleBlocks(blocks, sections, new Set(["h1"]), sectionMap);
    // copyright (before heading), h1 + p1 (expanded), h2 heading (always visible), table + p2 (collapsed)
    expect(result).toEqual([copyright, h1, p1, h2]);
  });

  it("shows footnotes block when its section is expanded", () => {
    const fn = { type: "footnotes", id: "fn", items: [], audio_chunks: [] } as ContentBlock;
    const sections = [makeSection("fn", 10, 12)];
    const result = filterVisibleBlocks([fn], sections, new Set(["fn"]), new Map());
    expect(result).toEqual([fn]);
  });

  it("hides footnotes block when its section is collapsed", () => {
    const fn = { type: "footnotes", id: "fn", items: [], audio_chunks: [] } as ContentBlock;
    const sections = [makeSection("fn", 10, 12)];
    const result = filterVisibleBlocks([fn], sections, new Set(), new Map());
    expect(result).toEqual([]);
  });
});

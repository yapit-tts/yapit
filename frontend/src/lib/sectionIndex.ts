// Section index utilities for document outliner
// Builds a hierarchical index of H1/H2 sections with H3+ subsections

// Re-declare types here to avoid circular dependencies with structuredDocument.tsx
// These match the backend Pydantic models

interface AudioChunk {
  text: string;
  audio_block_idx: number;
  ast?: InlineContent[];
}

type InlineContent =
  | { type: "text"; content: string }
  | { type: "code_span"; content: string }
  | { type: "strong"; content: InlineContent[] }
  | { type: "emphasis"; content: InlineContent[] }
  | { type: "link"; href: string; title?: string; content: InlineContent[] }
  | { type: "inline_image"; src: string; alt: string }
  | { type: "math_inline"; content: string }
  | { type: "speak"; content: string }
  | { type: "show"; content: InlineContent[] }
  | { type: "footnote_ref"; label: string; has_content: boolean };

interface HeadingBlock {
  type: "heading";
  id: string;
  level: 1 | 2 | 3 | 4 | 5 | 6;
  html: string;
  ast: InlineContent[];
  audio_chunks: AudioChunk[];
}

interface ContentBlock {
  type: string;
  id: string;
  audio_chunks?: AudioChunk[];
}

interface StructuredDocument {
  version: string;
  blocks: ContentBlock[];
}

// Exported types for outliner

export interface Subsection {
  id: string;
  title: string;
  level: 3 | 4 | 5 | 6;
  blockIdx: number; // Audio block index to jump to
}

export interface Section {
  id: string;
  title: string;
  level: 1 | 2;
  startBlockIdx: number; // First audio block (inclusive)
  endBlockIdx: number; // Last audio block (inclusive)
  durationMs: number; // Sum of est_duration_ms for section blocks
  subsections: Subsection[];
}

// Extract plain text from heading AST (matches structuredDocument.tsx logic)
function extractTextFromAst(nodes: InlineContent[]): string {
  return nodes
    .map((node) => {
      switch (node.type) {
        case "text":
        case "code_span":
          return node.content;
        case "strong":
        case "emphasis":
        case "link":
          return extractTextFromAst(node.content);
        case "inline_image":
          return node.alt;
        case "math_inline":
        case "speak":
        case "footnote_ref":
          return "";
        default:
          return "";
      }
    })
    .join("");
}

interface DocumentBlock {
  id: string | number;
  est_duration_ms?: number;
}

/**
 * Build section index from structured content.
 * Sections are defined by H1/H2 headings.
 * H3+ become subsections within the preceding section.
 *
 * @param structuredContent - Parsed JSON from document's structured_content field
 * @param documentBlocks - Array of document blocks with est_duration_ms
 * @returns Array of sections, empty if no H1/H2 headings exist
 */
export function buildSectionIndex(
  structuredContent: StructuredDocument,
  documentBlocks: DocumentBlock[]
): Section[] {
  const sections: Section[] = [];
  const blocks = structuredContent.blocks;

  // First pass: find all H1/H2 headings and their positions
  const majorHeadings: {
    block: HeadingBlock;
    blockIndex: number;
    audioBlockIdx: number;
  }[] = [];

  for (let i = 0; i < blocks.length; i++) {
    const block = blocks[i];
    if (block.type === "heading") {
      const heading = block as HeadingBlock;
      if (heading.level <= 2 && heading.audio_chunks?.length > 0) {
        majorHeadings.push({
          block: heading,
          blockIndex: i,
          audioBlockIdx: heading.audio_chunks[0].audio_block_idx,
        });
      }
    }
  }

  if (majorHeadings.length === 0) {
    return [];
  }

  // Second pass: build sections with subsections and calculate durations
  for (let i = 0; i < majorHeadings.length; i++) {
    const current = majorHeadings[i];
    const next = majorHeadings[i + 1];

    const startBlockIdx = current.audioBlockIdx;
    const endBlockIdx = next
      ? next.audioBlockIdx - 1
      : documentBlocks.length - 1;

    // Find H3+ subsections within this section's block range
    const subsections: Subsection[] = [];
    const endContentIdx = next ? next.blockIndex : blocks.length;

    for (let j = current.blockIndex + 1; j < endContentIdx; j++) {
      const block = blocks[j];
      if (block.type === "heading") {
        const heading = block as HeadingBlock;
        if (heading.level >= 3 && heading.audio_chunks?.length > 0) {
          subsections.push({
            id: heading.id,
            title: extractTextFromAst(heading.ast),
            level: heading.level as 3 | 4 | 5 | 6,
            blockIdx: heading.audio_chunks[0].audio_block_idx,
          });
        }
      }
    }

    // Calculate duration for this section
    let durationMs = 0;
    for (let j = startBlockIdx; j <= endBlockIdx && j < documentBlocks.length; j++) {
      durationMs += documentBlocks[j]?.est_duration_ms ?? 0;
    }

    sections.push({
      id: current.block.id,
      title: extractTextFromAst(current.block.ast),
      level: current.block.level as 1 | 2,
      startBlockIdx,
      endBlockIdx,
      durationMs,
      subsections,
    });
  }

  return sections;
}

/**
 * Find which section contains a given block index.
 *
 * @param sections - Section index from buildSectionIndex
 * @param blockIdx - Audio block index
 * @returns The section containing this block, or null if not found
 */
export function findSectionForBlock(
  sections: Section[],
  blockIdx: number
): Section | null {
  for (const section of sections) {
    if (blockIdx >= section.startBlockIdx && blockIdx <= section.endBlockIdx) {
      return section;
    }
  }
  return null;
}

/**
 * Format duration in human-readable form.
 *
 * @param ms - Duration in milliseconds
 * @returns Formatted string like "~15m", "~1h 23m", "~2h"
 */
export function formatDuration(ms: number): string {
  const totalMinutes = Math.round(ms / 60000);

  if (totalMinutes < 1) {
    return "<1m";
  }

  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;

  if (hours === 0) {
    return `${minutes}m`;
  }

  if (minutes === 0) {
    return `~${hours}h`;
  }

  return `${hours}h ${minutes}m`;
}

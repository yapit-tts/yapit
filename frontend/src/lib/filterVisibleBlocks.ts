import type { ContentBlock } from "@/components/structuredDocument";
import type { Section } from "@/lib/sectionIndex";
import { perfStart } from "@/lib/perfMonitor";

/**
 * Filter document blocks based on section expand/collapse state.
 * Collapsed sections are hidden from the document view (heading stays visible).
 *
 * Rules:
 * - Section headings are always visible (collapsed ones render grayed)
 * - Footnotes block visible only if its section is expanded
 * - Blocks with audio inherit visibility from their section
 * - Display-only blocks (no audio_chunks) inherit visibility from the
 *   last seen section, OR are always visible if before the first heading
 */
export function filterVisibleBlocks(
  blocks: ContentBlock[],
  sections: Section[],
  expandedSections: Set<string>,
  sectionByHeadingId: Map<string, Section>,
): ContentBlock[] {
  const end = perfStart('filterVisibleBlocks');
  const sectionById = new Map(sections.map(s => [s.id, s]));

  // Precompute audioIdx → Section map (O(total block range) build, O(1) lookup)
  const sectionByAudioIdx = new Map<number, Section>();
  for (const s of sections) {
    for (let idx = s.startBlockIdx; idx <= s.endBlockIdx; idx++) {
      sectionByAudioIdx.set(idx, s);
    }
  }

  const visible: ContentBlock[] = [];
  let lastSeenSectionId: string | null = null;

  for (const block of blocks) {
    // Footnotes block acts as a section header (synthetic section created in buildSectionIndex)
    if (block.type === "footnotes" && sectionById.has(block.id)) {
      lastSeenSectionId = block.id;
      if (expandedSections.has(block.id)) {
        visible.push(block);
      }
      continue;
    }

    // Section headings are always visible (collapsed ones render grayed with chevron)
    if (block.type === "heading" && sectionByHeadingId.has(block.id)) {
      lastSeenSectionId = block.id;
      visible.push(block);
      continue;
    }

    const audioIdx = block.audio_chunks?.[0]?.audio_block_idx;
    if (audioIdx === undefined) {
      if (!lastSeenSectionId || expandedSections.has(lastSeenSectionId)) {
        visible.push(block);
      }
      continue;
    }

    const section = sectionByAudioIdx.get(audioIdx);
    if (!section) {
      // Preamble: audio blocks before the first section heading — always visible
      if (!lastSeenSectionId) {
        visible.push(block);
      }
      continue;
    }

    if (section.id !== lastSeenSectionId) {
      lastSeenSectionId = section.id;
    }

    if (expandedSections.has(section.id)) {
      visible.push(block);
    }
  }

  end();
  return visible;
}

import type { ContentBlock } from "@/components/structuredDocument";
import type { Section } from "@/lib/sectionIndex";

/**
 * Filter document blocks based on section expand/collapse state.
 *
 * Rules:
 * - Footnotes are always visible
 * - Section headings are visible unless skipped
 * - Blocks with audio inherit visibility from their section
 * - Display-only blocks (no audio_chunks) inherit visibility from the
 *   last seen section, OR are always visible if before the first heading
 */
export function filterVisibleBlocks(
  blocks: ContentBlock[],
  sections: Section[],
  expandedSections: Set<string>,
  skippedSections: Set<string>,
  sectionByHeadingId: Map<string, Section>,
): ContentBlock[] {
  const findSectionForAudioIdx = (audioIdx: number): Section | undefined => {
    return sections.find(
      (s) => audioIdx >= s.startBlockIdx && audioIdx <= s.endBlockIdx,
    );
  };

  const visible: ContentBlock[] = [];
  let lastSeenSectionId: string | null = null;

  for (const block of blocks) {
    if (block.type === "footnotes") {
      visible.push(block);
      continue;
    }

    if (block.type === "heading" && sectionByHeadingId.has(block.id)) {
      const sectionId = block.id;
      if (skippedSections.has(sectionId)) {
        lastSeenSectionId = sectionId;
        continue;
      }
      visible.push(block);
      lastSeenSectionId = sectionId;
      continue;
    }

    const audioIdx = block.audio_chunks?.[0]?.audio_block_idx;
    if (audioIdx === undefined) {
      // Display-only blocks (code, table, hr, yap-show content):
      // Show if before any heading, or if their section is expanded
      if (
        !lastSeenSectionId ||
        (expandedSections.has(lastSeenSectionId) &&
          !skippedSections.has(lastSeenSectionId))
      ) {
        visible.push(block);
      }
      continue;
    }

    const section = findSectionForAudioIdx(audioIdx);
    if (!section) continue;

    if (section.id !== lastSeenSectionId) {
      lastSeenSectionId = section.id;
    }

    if (
      expandedSections.has(section.id) &&
      !skippedSections.has(section.id)
    ) {
      visible.push(block);
    }
  }

  return visible;
}

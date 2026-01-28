import { useMemo } from "react";
import type { Section } from "@/lib/sectionIndex";

type BlockState = "pending" | "synthesizing" | "cached";

interface Block {
  id: number;
  idx: number;
  est_duration_ms: number;
}

export interface FilteredPlayback {
  // Filtered data for progress bar
  filteredBlockStates: BlockState[];
  filteredDuration: number;
  filteredBlockCount: number;

  // Index translation
  visualToAbsolute: (visualIdx: number) => number;
  absoluteToVisual: (absoluteIdx: number) => number | null;

  // Current block position
  visualCurrentBlock: number | null; // null if current block is in collapsed section
  isCurrentBlockHidden: boolean;

  // Elapsed time (sum of visible blocks before current)
  filteredElapsedMs: number;
}

/**
 * Derives filtered playback data based on expanded and skipped sections.
 *
 * When sections are collapsed or skipped in the outliner, their blocks are
 * excluded from the progress bar. This hook handles the filtering and provides
 * bidirectional index mapping for click-to-seek.
 *
 * A block is visible if its section is expanded AND not skipped.
 */
export function useFilteredPlayback(
  documentBlocks: Block[],
  sections: Section[],
  expandedSections: Set<string>,
  blockStates: BlockState[],
  currentBlock: number,
  skippedSections?: Set<string>
): FilteredPlayback {
  return useMemo(() => {
    // No sections = no filtering, return identity mapping
    if (sections.length === 0) {
      // Calculate elapsed time: sum of blocks before currentBlock
      let elapsedMs = 0;
      for (let i = 0; i < currentBlock && i < documentBlocks.length; i++) {
        elapsedMs += documentBlocks[i]?.est_duration_ms ?? 0;
      }
      return {
        filteredBlockStates: blockStates,
        filteredDuration: documentBlocks.reduce((sum, b) => sum + (b.est_duration_ms ?? 0), 0),
        filteredBlockCount: documentBlocks.length,
        visualToAbsolute: (idx: number) => idx,
        absoluteToVisual: (idx: number) => idx,
        visualCurrentBlock: currentBlock >= 0 ? currentBlock : null,
        isCurrentBlockHidden: false,
        filteredElapsedMs: elapsedMs,
      };
    }

    const skipped = skippedSections ?? new Set<string>();

    // Build set of visible absolute block indices
    // A block is visible if its section is expanded AND not skipped
    const visibleAbsoluteIndices: number[] = [];
    const absoluteToVisualMap = new Map<number, number>();

    for (const section of sections) {
      if (!expandedSections.has(section.id)) continue;
      if (skipped.has(section.id)) continue;

      for (let absIdx = section.startBlockIdx; absIdx <= section.endBlockIdx; absIdx++) {
        if (absIdx >= 0 && absIdx < documentBlocks.length) {
          absoluteToVisualMap.set(absIdx, visibleAbsoluteIndices.length);
          visibleAbsoluteIndices.push(absIdx);
        }
      }
    }

    // Build filtered states and calculate duration
    const filteredBlockStates: BlockState[] = [];
    let filteredDuration = 0;

    for (const absIdx of visibleAbsoluteIndices) {
      filteredBlockStates.push(blockStates[absIdx] ?? "pending");
      filteredDuration += documentBlocks[absIdx]?.est_duration_ms ?? 0;
    }

    // Index translation functions
    const visualToAbsolute = (visualIdx: number): number => {
      if (visualIdx < 0 || visualIdx >= visibleAbsoluteIndices.length) {
        return visualIdx; // Fallback to identity
      }
      return visibleAbsoluteIndices[visualIdx];
    };

    const absoluteToVisual = (absIdx: number): number | null => {
      return absoluteToVisualMap.get(absIdx) ?? null;
    };

    // Current block visual position
    const visualCurrentBlock = currentBlock >= 0 ? absoluteToVisualMap.get(currentBlock) ?? null : null;
    const isCurrentBlockHidden = currentBlock >= 0 && visualCurrentBlock === null;

    // Calculate elapsed time: sum of visible blocks before visualCurrentBlock
    let filteredElapsedMs = 0;
    if (visualCurrentBlock !== null && visualCurrentBlock > 0) {
      for (let i = 0; i < visualCurrentBlock; i++) {
        const absIdx = visibleAbsoluteIndices[i];
        filteredElapsedMs += documentBlocks[absIdx]?.est_duration_ms ?? 0;
      }
    }

    return {
      filteredBlockStates,
      filteredDuration,
      filteredBlockCount: visibleAbsoluteIndices.length,
      visualToAbsolute,
      absoluteToVisual,
      visualCurrentBlock,
      isCurrentBlockHidden,
      filteredElapsedMs,
    };
  }, [documentBlocks, sections, expandedSections, blockStates, currentBlock, skippedSections]);
}

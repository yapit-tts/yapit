import { useMemo } from "react";
import type { Section } from "@/lib/sectionIndex";
import { perfStart } from "@/lib/perfMonitor";

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
 * Derives filtered playback data based on section expand/collapse state.
 *
 * Collapsed sections are excluded from the progress bar. This hook handles
 * the filtering and provides bidirectional index mapping for click-to-seek.
 */
export function useFilteredPlayback(
  documentBlocks: Block[],
  sections: Section[],
  expandedSections: Set<string>,
  blockStates: BlockState[],
  currentBlock: number,
): FilteredPlayback {
  return useMemo(() => {
    const end = perfStart('useFilteredPlayback');
    // No sections = no filtering, return identity mapping
    if (sections.length === 0) {
      let elapsedMs = 0;
      for (let i = 0; i < currentBlock && i < documentBlocks.length; i++) {
        elapsedMs += documentBlocks[i]?.est_duration_ms ?? 0;
      }
      const result = {
        filteredBlockStates: blockStates,
        filteredDuration: documentBlocks.reduce((sum, b) => sum + (b.est_duration_ms ?? 0), 0),
        filteredBlockCount: documentBlocks.length,
        visualToAbsolute: (idx: number) => idx,
        absoluteToVisual: (idx: number) => idx,
        visualCurrentBlock: currentBlock >= 0 ? currentBlock : null,
        isCurrentBlockHidden: false,
        filteredElapsedMs: elapsedMs,
      };
      end();
      return result;
    }

    // Build set of visible absolute block indices (expanded sections only)
    const visibleAbsoluteIndices: number[] = [];
    const absoluteToVisualMap = new Map<number, number>();

    for (const section of sections) {
      if (!expandedSections.has(section.id)) continue;

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

    const visualToAbsolute = (visualIdx: number): number => {
      if (visualIdx < 0 || visualIdx >= visibleAbsoluteIndices.length) {
        return visualIdx;
      }
      return visibleAbsoluteIndices[visualIdx];
    };

    const absoluteToVisual = (absIdx: number): number | null => {
      return absoluteToVisualMap.get(absIdx) ?? null;
    };

    const visualCurrentBlock = currentBlock >= 0 ? absoluteToVisualMap.get(currentBlock) ?? null : null;
    const isCurrentBlockHidden = currentBlock >= 0 && visualCurrentBlock === null;

    let filteredElapsedMs = 0;
    if (visualCurrentBlock !== null && visualCurrentBlock > 0) {
      for (let i = 0; i < visualCurrentBlock; i++) {
        const absIdx = visibleAbsoluteIndices[i];
        filteredElapsedMs += documentBlocks[absIdx]?.est_duration_ms ?? 0;
      }
    }

    const result = {
      filteredBlockStates,
      filteredDuration,
      filteredBlockCount: visibleAbsoluteIndices.length,
      visualToAbsolute,
      absoluteToVisual,
      visualCurrentBlock,
      isCurrentBlockHidden,
      filteredElapsedMs,
    };
    end();
    return result;
  }, [documentBlocks, sections, expandedSections, blockStates, currentBlock]);
}

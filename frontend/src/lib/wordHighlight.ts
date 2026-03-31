import type { WordTiming } from "./playbackEngine";

const HIGHLIGHT_NAME = "audio-word-active";

export function createWordHighlightManager() {
  const isSupported = typeof CSS !== "undefined" && "highlights" in CSS;
  let prebuiltRanges: Range[] | null = null;
  let prebuiltBlockIdx = -1;

  function buildRanges(container: Element, timings: WordTiming[]): Range[] {
    const ranges: Range[] = [];
    const textNodes: Text[] = [];
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
    let node: Text | null;
    while ((node = walker.nextNode() as Text | null)) textNodes.push(node);

    let nodeIdx = 0;
    let searchFrom = 0;

    for (let wordPointer = 0; wordPointer < timings.length; wordPointer++) {
      const wordText = timings[wordPointer].t.trim();
      if (!wordText) { ranges.push(null!); continue; }

      let found = false;
      for (let n = nodeIdx; n < textNodes.length; n++) {
        const text = textNodes[n].textContent || "";
        const start = n === nodeIdx ? searchFrom : 0;
        const idx = text.indexOf(wordText, start);
        if (idx !== -1) {
          const range = document.createRange();
          range.setStart(textNodes[n], idx);
          range.setEnd(textNodes[n], idx + wordText.length);
          ranges.push(range);
          nodeIdx = n;
          searchFrom = idx + wordText.length;
          found = true;
          break;
        }
      }
      if (!found) ranges.push(null!);
    }
    return ranges;
  }

  function update(blockIdx: number, wordIdx: number, timings: WordTiming[]) {
    if (!isSupported) return;
    if (prebuiltBlockIdx !== blockIdx) {
      const el = document.querySelector(`[data-audio-idx="${blockIdx}"]`)
              ?? document.querySelector(`[data-audio-block-idx="${blockIdx}"]`);
      if (!el) return;
      prebuiltRanges = buildRanges(el, timings);
      prebuiltBlockIdx = blockIdx;
    }
    const range = prebuiltRanges?.[wordIdx];
    if (!range) return;
    // @ts-expect-error CSS.highlights is not yet in all TS lib types
    CSS.highlights.set(HIGHLIGHT_NAME, new Highlight(range));
  }

  function clear() {
    if (!isSupported) return;
    // @ts-expect-error CSS.highlights is not yet in all TS lib types
    CSS.highlights?.delete(HIGHLIGHT_NAME);
    prebuiltRanges = null;
    prebuiltBlockIdx = -1;
  }

  return { update, clear, isSupported };
}

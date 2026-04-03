import type { AudioPlayer } from "./audio";
import type { Section } from "./sectionIndex";
import { findSectionForBlock } from "./sectionIndex";
import type { Synthesizer } from "./synthesizer";
import { perfStart } from "./perfMonitor";

// --- Types ---

export interface Block {
  idx: number;
  text: string;
  est_duration_ms: number;
}

export interface WordTiming {
  t: string;  // word text
  s: number;  // start (seconds)
  e: number;  // end (seconds)
}

export interface AudioBufferData {
  buffer?: AudioBuffer;
  rawAudio?: ArrayBuffer;
  duration_ms: number;
  wordTimings?: WordTiming[];
}

export type BlockVisualState = "pending" | "synthesizing" | "cached";

type PlaybackStatus = "stopped" | "buffering" | "playing";

export interface PlaybackSnapshot {
  status: PlaybackStatus;
  currentBlock: number;
  isSynthesizingCurrent: boolean;
  blockStates: BlockVisualState[];
  audioProgress: number;
  totalDuration: number;

}

// --- Configuration ---

const BATCH_SIZE = 8;
const REFILL_THRESHOLD = 8;
const MIN_BUFFER_TO_START = 1;
const EVICT_BEHIND = 32;

// --- Variant key: `${blockIdx}:${model}:${voice}` ---

type VariantKey = string;

function variantKey(blockIdx: number, model: string, voice: string): VariantKey {
  return `${blockIdx}:${model}:${voice}`;
}

// --- Engine dependencies (injected for testability) ---

export interface PlaybackEngineDeps {
  audioPlayer: AudioPlayer;
  synthesizer: Synthesizer;
}

// --- Public interface ---

export interface PlaybackEngine {
  play(): void;
  pause(): void;
  stop(): void;
  skipForward(): void;
  skipBack(): void;
  seekToBlock(blockIdx: number): void;
  setVoice(model: string, voiceSlug: string): void;
  setDocument(documentId: string, blocks: Block[]): void;
  setPlaybackSpeed(speed: number): void;
  setVolume(volume: number): void;
  setSections(sections: Section[], skippedSections: Set<string>): void;
  setSynthesizer(synthesizer: Synthesizer): void;
  subscribe(listener: () => void): () => void;
  getSnapshot(): PlaybackSnapshot;
  restorePosition(block: number): void;
  setOnWordChange(cb: ((blockIdx: number, wordIdx: number) => void) | null): void;
  getWordTimingsForBlock(blockIdx: number): WordTiming[] | undefined;
  destroy(): void;
}

// --- Factory ---

export function createPlaybackEngine(deps: PlaybackEngineDeps): PlaybackEngine {
  let synthesizer = deps.synthesizer;

  // --- Mutable state ---
  let status: PlaybackStatus = "stopped";
  let currentBlock = -1;
  let isSynthesizingCurrent = false;
  let documentId: string | null = null;
  let blocks: Block[] = [];
  let model: string = "";
  let voiceSlug: string = "";
  let sections: Section[] = [];
  let skippedSections = new Set<string>();

  let blockStartTime = 0;
  let audioProgress = 0;
  let totalDuration = 0;
  let initialTotalEstimate = 0;
  const durationCorrections = new Map<number, number>();

  const audioCache = new Map<VariantKey, AudioBufferData>();
  const synthesisPromises = new Map<VariantKey, Promise<AudioBufferData | null>>();
  const knownCached = new Set<VariantKey>();
  const resolvedEmpty = new Set<VariantKey>();

  let prefetchedUpTo = -1;

  let listeners: Array<() => void> = [];
  let snapshot: PlaybackSnapshot | null = null;

  // --- Word-level tracking ---
  let onWordChangeCallback: ((blockIdx: number, wordIdx: number) => void) | null = null;
  let currentWordIdx = -1;
  let wordAnimFrame: number | null = null;

  function startWordTracking(audioData: AudioBufferData) {
    stopWordTracking();
    if (!audioData.wordTimings?.length || !onWordChangeCallback) return;
    const timings = audioData.wordTimings;

    function tick() {
      if (status !== "playing") return;
      const t = deps.audioPlayer.getCurrentTime();

      // Binary search for active word
      let lo = 0, hi = timings.length - 1, idx = -1;
      while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        if (timings[mid].e <= t) lo = mid + 1;
        else if (timings[mid].s > t) hi = mid - 1;
        else { idx = mid; break; }
      }

      if (idx !== currentWordIdx) {
        currentWordIdx = idx;
        if (idx >= 0) onWordChangeCallback!(currentBlock, idx);
      }
      wordAnimFrame = requestAnimationFrame(tick);
    }
    wordAnimFrame = requestAnimationFrame(tick);
  }

  function stopWordTracking() {
    if (wordAnimFrame !== null) { cancelAnimationFrame(wordAnimFrame); wordAnimFrame = null; }
    currentWordIdx = -1;
  }

  // deriveBlockStates cache — only recompute when underlying maps change
  let blockStatesVersion = 0;
  let cachedBlockStates: BlockVisualState[] | null = null;
  let cachedBlockStatesVersion = -1;

  function invalidateBlockStates() { blockStatesVersion++; }

  deps.audioPlayer.setOnProgress((percentPlayed, blockDurationMs) => {
    const blockProgress = (percentPlayed / 100) * blockDurationMs;
    audioProgress = blockStartTime + blockProgress;
  });

  // --- Helpers ---

  function setStatus(newStatus: PlaybackStatus, trigger: string) {
    if (status === newStatus) return;
    console.debug(`[PlaybackEngine] ${status}→${newStatus}`, { trigger, currentBlock });
    status = newStatus;
  }

  function notify() {
    snapshot = null;
    for (const listener of listeners) listener();
  }

  function currentVariantKey(blockIdx: number): VariantKey {
    return variantKey(blockIdx, model, voiceSlug);
  }

  function isBlockSkipped(blockIdx: number): boolean {
    if (sections.length === 0 || skippedSections.size === 0) return false;
    const section = findSectionForBlock(sections, blockIdx);
    return section ? skippedSections.has(section.id) : false;
  }

  function findNextPlayable(fromIdx: number): number {
    for (let idx = fromIdx; idx < blocks.length; idx++) {
      if (!isBlockSkipped(idx)) return idx;
    }
    return -1;
  }

  function findPrevPlayable(fromIdx: number): number {
    for (let idx = fromIdx; idx >= 0; idx--) {
      if (!isBlockSkipped(idx)) return idx;
    }
    return -1;
  }

  function getBlockAudio(blockIdx: number): AudioBufferData | undefined {
    return audioCache.get(currentVariantKey(blockIdx));
  }

  function recalcTotalDuration() {
    const totalCorrection = Array.from(durationCorrections.values()).reduce((sum, c) => sum + c, 0);
    totalDuration = initialTotalEstimate + totalCorrection;
  }

  function recordDurationCorrection(block: Block, actualDurationMs: number) {
    const correction = actualDurationMs - (block.est_duration_ms || 0);
    durationCorrections.set(block.idx, correction);
    recalcTotalDuration();
  }

  function calcProgressToBlock(blockIdx: number): number {
    let ms = 0;
    for (let i = 0; i < blockIdx && i < blocks.length; i++) {
      if (isBlockSkipped(i)) continue;
      const audio = getBlockAudio(i);
      ms += audio?.duration_ms || blocks[i].est_duration_ms || 0;
    }
    return ms;
  }

  // --- Audio playback ---

  async function playBlock(blockIdx: number) {
    if (blockIdx < 0 || blockIdx >= blocks.length) return;
    if (status !== "playing") return;

    if (isBlockSkipped(blockIdx)) {
      const next = findNextPlayable(blockIdx + 1);
      if (next >= 0) {
        currentBlock = next;
        blockStartTime = calcProgressToBlock(next);
        audioProgress = blockStartTime;
        notify();
        playBlock(next);
      } else {
        engineStop();
      }
      return;
    }

    const audio = getBlockAudio(blockIdx);
    console.debug("[PlaybackEngine] playBlock", { blockIdx, cached: !!audio });
    if (audio) {
      isSynthesizingCurrent = false;
      notify();
      await startAudioPlayback(audio);
    } else {
      isSynthesizingCurrent = true;
      notify();

      const audioData = await synthesizeBlock(blockIdx);
      if (currentBlock !== blockIdx || status !== "playing") {
        console.debug("[PlaybackEngine] playBlock: stale after synthesis", { blockIdx, currentBlock, status });
        return;
      }
      isSynthesizingCurrent = false;

      if (!audioData) {
        const err = synthesizer.getError();
        if (err && !synthesizer.isRecoverable()) {
          console.debug("[PlaybackEngine] playBlock: unrecoverable error, stopping", { blockIdx, error: err });
          engineStop();
          return;
        }
        console.debug("[PlaybackEngine] playBlock: block skipped/failed, advancing", { blockIdx, error: err });
        advanceToNext();
        return;
      }
      notify();
      await startAudioPlayback(audioData);
    }

    checkAndRefillBuffer();
    evictOldBlocks();
  }

  async function startAudioPlayback(audioData: AudioBufferData) {
    deps.audioPlayer.setOnEnded(() => {
      stopWordTracking();
      blockStartTime += audioData.duration_ms;
      advanceToNext();
    });
    try {
      if (audioData.rawAudio) {
        const actualMs = await deps.audioPlayer.loadRawAudio(audioData.rawAudio, "audio/ogg");
        audioData.duration_ms = actualMs;
        const blk = blocks[currentBlock];
        if (blk) recordDurationCorrection(blk, actualMs);
      } else if (audioData.buffer) {
        await deps.audioPlayer.load(audioData.buffer);
      }
      await deps.audioPlayer.play();
      startWordTracking(audioData);
      console.debug("[PlaybackEngine] startAudioPlayback: playing", { blockIdx: currentBlock });
    } catch (err) {
      console.error("[PlaybackEngine] Audio playback failed, skipping block:", err);
      advanceToNext();
    }
  }

  function advanceToNext() {
    const next = findNextPlayable(currentBlock + 1);
    console.debug("[PlaybackEngine] advanceToNext", { from: currentBlock, to: next });
    if (next >= 0) {
      currentBlock = next;
      blockStartTime = calcProgressToBlock(next);
      audioProgress = blockStartTime;
  
      notify();
      playBlock(next);
    } else {
      engineStop();
    }
  }

  function engineStop() {
    stopWordTracking();
    setStatus("stopped", "engineStop");
    isSynthesizingCurrent = false;
    notify();
  }

  // --- Synthesis coordination ---

  function synthesizeBlock(blockIdx: number): Promise<AudioBufferData | null> {
    const key = currentVariantKey(blockIdx);

    const cached = audioCache.get(key);
    if (cached) return Promise.resolve(cached);

    const existing = synthesisPromises.get(key);
    if (existing) return existing;

    const block = blocks[blockIdx];
    if (!block || !documentId) return Promise.resolve(null);

    const promise = synthesizer.synthesize(blockIdx, block.text, documentId, model, voiceSlug)
      .then((result) => {
        synthesisPromises.delete(key);
        invalidateBlockStates();
        if (result) {
          audioCache.set(key, result);
          knownCached.add(key);
          invalidateBlockStates();
          const blk = blocks[blockIdx];
          if (blk && result.duration_ms > 0) recordDurationCorrection(blk, result.duration_ms);
          checkBufferReady();
        } else {
          resolvedEmpty.add(key);
          if (status === "buffering" && synthesizer.getError() && !synthesizer.isRecoverable()) {
            engineStop();
          } else {
            checkBufferReady();
          }
        }
        notify();
        return result;
      })
      .catch(() => {
        synthesisPromises.delete(key);
        invalidateBlockStates();
        notify();
        return null;
      });

    synthesisPromises.set(key, promise);
    invalidateBlockStates();
    return promise;
  }

  // --- Prefetch ---

  function triggerPrefetch(fromIdx: number, count: number) {
    if (!blocks.length || !documentId) return;
    const maxIdx = Math.min(fromIdx + count - 1, blocks.length - 1);

    for (let idx = fromIdx; idx <= maxIdx; idx++) {
      const key = currentVariantKey(idx);
      if (audioCache.has(key) || synthesisPromises.has(key)) continue;
      synthesizeBlock(idx);
    }

    if (maxIdx > prefetchedUpTo) prefetchedUpTo = maxIdx;
  }

  function checkAndRefillBuffer() {
    if (!blocks.length) return;

    let readyAhead = 0;
    for (let idx = currentBlock + 1; idx < blocks.length; idx++) {
      const key = currentVariantKey(idx);
      if (audioCache.has(key) || synthesisPromises.has(key)) { readyAhead++; continue; }
      break;
    }

    if (readyAhead >= REFILL_THRESHOLD) return;

    let firstUnready = currentBlock + 1;
    for (let idx = currentBlock + 1; idx < blocks.length; idx++) {
      const key = currentVariantKey(idx);
      if (audioCache.has(key) || synthesisPromises.has(key)) continue;
      firstUnready = idx;
      break;
    }

    if (firstUnready < blocks.length) {
      triggerPrefetch(firstUnready, BATCH_SIZE);
    }
  }

  function evictOldBlocks() {
    if (currentBlock <= EVICT_BEHIND) return;
    let evicted = false;
    for (let i = 0; i < currentBlock - EVICT_BEHIND; i++) {
      if (audioCache.delete(currentVariantKey(i))) evicted = true;
    }
    if (evicted) invalidateBlockStates();
  }

  // --- Buffer readiness check (for buffering → playing transition) ---

  function checkBufferReady() {
    if (status !== "buffering") return;
    const startBlock = currentBlock >= 0 ? currentBlock : 0;
    const cachedAhead = countCachedAhead(startBlock);
    const remaining = blocks.length - startBlock;
    const required = Math.min(MIN_BUFFER_TO_START, remaining);
    console.debug("[PlaybackEngine] checkBufferReady", { cachedAhead, required, startBlock });
    if (cachedAhead >= required) {
      setStatus("playing", "checkBufferReady");
      notify();
      playBlock(currentBlock);
    }
  }

  function countCachedAhead(fromIdx: number): number {
    let count = 0;
    for (let idx = fromIdx; idx < blocks.length; idx++) {
      const key = currentVariantKey(idx);
      if (audioCache.has(key) || resolvedEmpty.has(key)) {
        count++;
      } else {
        break;
      }
    }
    return count;
  }

  // --- Derive block visual states ---

  function deriveBlockStates(): BlockVisualState[] {
    if (cachedBlockStates && cachedBlockStatesVersion === blockStatesVersion) {
      return cachedBlockStates;
    }
    const end = perfStart('deriveBlockStates');
    const result = blocks.map((_block, idx) => {
      const key = currentVariantKey(idx);
      if (audioCache.has(key) || knownCached.has(key)) return "cached";
      if (synthesisPromises.has(key)) return "synthesizing";
      return "pending";
    });
    end();
    cachedBlockStates = result;
    cachedBlockStatesVersion = blockStatesVersion;
    return result;
  }

  // --- Public API ---

  function resetSynthesis(target: number) {
    synthesizer.cancelAll();
    if (synthesisPromises.size > 0) {
      synthesisPromises.clear();
      invalidateBlockStates();
    }
    prefetchedUpTo = -1;
    if (documentId) synthesizer.onCursorMove?.(documentId, target);
  }

  function moveCursor(target: number) {
    const wasPlaying = status === "playing";
    const wasBuffering = status === "buffering";

    stopWordTracking();
    deps.audioPlayer.stop();
    resetSynthesis(target);

    currentBlock = target;
    blockStartTime = calcProgressToBlock(target);
    audioProgress = blockStartTime;
    notify();

    if (wasPlaying) {
      playBlock(target);
    } else if (wasBuffering) {
      triggerPrefetch(target, BATCH_SIZE);
    }
  }

  function play() {
    console.debug("[PlaybackEngine] play()", { status, currentBlock, model, voiceSlug });
    if (status === "playing" || status === "buffering") return;
    if (!blocks.length) return;

    synthesizer.clearError();

    let startBlock = currentBlock;
    if (currentBlock === -1) {
      startBlock = findNextPlayable(0);
      if (startBlock < 0) return;
      currentBlock = startBlock;
      audioProgress = 0;
      blockStartTime = 0;
    } else if (isBlockSkipped(currentBlock)) {
      startBlock = findNextPlayable(currentBlock + 1);
      if (startBlock < 0) startBlock = findNextPlayable(0);
      if (startBlock < 0) return;
      currentBlock = startBlock;
    }

    const cachedAhead = countCachedAhead(startBlock);
    const remaining = blocks.length - startBlock;
    const required = Math.min(MIN_BUFFER_TO_START, remaining);

    if (cachedAhead >= required) {
      setStatus("playing", "play");
      notify();
      triggerPrefetch(startBlock + 1, BATCH_SIZE);
      playBlock(currentBlock);
    } else {
      setStatus("buffering", "play");
      notify();
      triggerPrefetch(startBlock, BATCH_SIZE);
    }
  }

  function pause() {
    if (status !== "playing") return;
    stopWordTracking();
    deps.audioPlayer.pause();
    setStatus("stopped", "pause");
    isSynthesizingCurrent = false;
    notify();
  }

  function stop_() {
    deps.audioPlayer.stop();
    setStatus("stopped", "stop");
    isSynthesizingCurrent = false;
    resetSynthesis(currentBlock);
    notify();
  }

  function skipForward() {
    if (!blocks.length || currentBlock >= blocks.length - 1) return;
    const next = findNextPlayable(currentBlock + 1);
    if (next < 0) return;
    moveCursor(next);
  }

  function skipBack() {
    if (currentBlock < 0 || !blocks.length) return;
    const prev = findPrevPlayable(currentBlock - 1);
    const target = prev >= 0 ? prev : findNextPlayable(0);
    if (target < 0) return;
    moveCursor(target);
  }

  function seekToBlock(blockIdx: number) {
    if (blockIdx < 0 || blockIdx >= blocks.length) return;
    moveCursor(blockIdx);
  }

  function setVoice(newModel: string, newVoiceSlug: string) {
    if (model === newModel && voiceSlug === newVoiceSlug) return;
    console.debug("[PlaybackEngine] setVoice", { from: `${model}/${voiceSlug}`, to: `${newModel}/${newVoiceSlug}` });

    const wasActive = status === "playing" || status === "buffering";
    const oldModel = model;
    const oldVoice = voiceSlug;

    model = newModel;
    voiceSlug = newVoiceSlug;

    // Evict old voice audio/visual state and cancel pending synthesis
    for (const key of audioCache.keys()) {
      if (key.includes(`:${oldModel}:${oldVoice}`)) audioCache.delete(key);
    }
    for (const key of knownCached) {
      if (key.includes(`:${oldModel}:${oldVoice}`)) knownCached.delete(key);
    }
    for (const key of resolvedEmpty) {
      if (key.includes(`:${oldModel}:${oldVoice}`)) resolvedEmpty.delete(key);
    }

    synthesizer.cancelAll();
    synthesisPromises.clear();
    invalidateBlockStates();

    durationCorrections.clear();
    recalcTotalDuration();
    prefetchedUpTo = -1;

    if (wasActive && currentBlock >= 0) {
      deps.audioPlayer.stop();

      setStatus("buffering", "setVoice");
      isSynthesizingCurrent = false;
      notify();
      triggerPrefetch(currentBlock, BATCH_SIZE);
    } else {
      notify();
    }
  }

  function setDocument(newDocumentId: string, newBlocks: Block[]) {
    deps.audioPlayer.stop();

    synthesizer.cancelAll();
    synthesisPromises.clear();

    documentId = newDocumentId;
    blocks = newBlocks;
    status = "stopped";
    currentBlock = -1;
    isSynthesizingCurrent = false;

    audioProgress = 0;
    blockStartTime = 0;
    prefetchedUpTo = -1;

    audioCache.clear();
    knownCached.clear();
    resolvedEmpty.clear();
    invalidateBlockStates();
    durationCorrections.clear();

    initialTotalEstimate = newBlocks.reduce((sum, b) => sum + (b.est_duration_ms || 0), 0);
    totalDuration = initialTotalEstimate;

    notify();
  }

  function setPlaybackSpeed(speed: number) {
    deps.audioPlayer.setTempo(speed);
  }

  function setVolume(volume: number) {
    deps.audioPlayer.setVolume(volume);
  }

  function setSections_(newSections: Section[], newSkipped: Set<string>) {
    sections = newSections;
    skippedSections = newSkipped;
  }

  function setSynthesizer_(newSynthesizer: Synthesizer) {
    synthesizer = newSynthesizer;
  }

  function restorePosition(block: number) {
    currentBlock = block;
    blockStartTime = calcProgressToBlock(block);
    audioProgress = blockStartTime;
    notify();
  }

  function destroy() {
    stopWordTracking();
    deps.audioPlayer.stop();
    synthesizer.cancelAll();
    synthesisPromises.clear();
    audioCache.clear();
    knownCached.clear();
    resolvedEmpty.clear();
    invalidateBlockStates();
    listeners = [];
  }

  // --- Snapshot ---

  function getSnapshot(): PlaybackSnapshot {
    if (snapshot) return snapshot;
    const end = perfStart('getSnapshot');
    snapshot = {
      status,
      currentBlock,
      isSynthesizingCurrent,
      blockStates: deriveBlockStates(),
      audioProgress,
      totalDuration,
    };
    end();
    return snapshot;
  }

  function subscribe(listener: () => void): () => void {
    listeners.push(listener);
    return () => { listeners = listeners.filter(l => l !== listener); };
  }

  function setOnWordChange(cb: ((blockIdx: number, wordIdx: number) => void) | null) {
    onWordChangeCallback = cb;
    if (!cb) stopWordTracking();
  }

  function getWordTimingsForBlock(blockIdx: number): WordTiming[] | undefined {
    return audioCache.get(currentVariantKey(blockIdx))?.wordTimings;
  }

  return {
    play,
    pause,
    stop: stop_,
    skipForward,
    skipBack,
    seekToBlock,
    setVoice,
    setDocument,
    setPlaybackSpeed,
    setVolume,
    setSections: setSections_,
    setSynthesizer: setSynthesizer_,
    subscribe,
    getSnapshot,
    restorePosition,
    setOnWordChange,
    getWordTimingsForBlock,
    destroy,
  };
}

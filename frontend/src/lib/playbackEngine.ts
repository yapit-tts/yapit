import type { AudioPlayer } from "./audio";
import type { Section } from "./sectionIndex";
import { findSectionForBlock } from "./sectionIndex";
import type { Synthesizer } from "./synthesizer";

// --- Types ---

export interface Block {
  id: number;
  idx: number;
  text: string;
  est_duration_ms: number;
}

export interface AudioBufferData {
  buffer?: AudioBuffer;
  rawAudio?: ArrayBuffer;
  duration_ms: number;
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
const MIN_BUFFER_TO_START = 2;
const EVICT_BEHIND = 20;

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
  getBlockStartTime(): number;
  restorePosition(block: number, progressMs: number): void;
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

  let prefetchedUpTo = -1;

  let listeners: Array<() => void> = [];
  let snapshot: PlaybackSnapshot | null = null;

  deps.audioPlayer.setOnProgress((percentPlayed, blockDurationMs) => {
    const blockProgress = (percentPlayed / 100) * blockDurationMs;
    audioProgress = blockStartTime + blockProgress;
    notify();
  });

  // --- Helpers ---

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
    durationCorrections.set(block.id, correction);
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
    if (audio) {
      isSynthesizingCurrent = false;
      notify();
      await startAudioPlayback(audio);
    } else {
      isSynthesizingCurrent = true;
      notify();

      const audioData = await synthesizeBlock(blockIdx);
      if (currentBlock !== blockIdx || status !== "playing") return;
      isSynthesizingCurrent = false;

      if (!audioData) {
        // Persistent error (e.g. usage limit) → stop instead of futilely trying every block
        if (synthesizer.getError()) {
          engineStop();
          return;
        }
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
    } catch (err) {
      console.error("[PlaybackEngine] Audio playback failed, skipping block:", err);
      advanceToNext();
    }
  }

  function advanceToNext() {
    const next = findNextPlayable(currentBlock + 1);
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
    status = "stopped";
    isSynthesizingCurrent = false;

    currentBlock = -1;
    audioProgress = 0;
    blockStartTime = 0;
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
        if (result) {
          audioCache.set(key, result);
          const blk = blocks[blockIdx];
          if (blk && result.duration_ms > 0) recordDurationCorrection(blk, result.duration_ms);
          checkBufferReady();
        } else if (status === "buffering" && synthesizer.getError()) {
          // Persistent error while buffering (e.g. usage limit) — buffer will never fill
          engineStop();
        }
        notify();
        return result;
      })
      .catch(() => {
        synthesisPromises.delete(key);
        notify();
        return null;
      });

    synthesisPromises.set(key, promise);
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
    for (let i = 0; i < currentBlock - EVICT_BEHIND; i++) {
      audioCache.delete(currentVariantKey(i));
    }
  }

  // --- Buffer readiness check (for buffering → playing transition) ---

  function checkBufferReady() {
    if (status !== "buffering") return;
    const startBlock = currentBlock >= 0 ? currentBlock : 0;
    const cachedAhead = countCachedAhead(startBlock);
    const remaining = blocks.length - startBlock;
    const required = Math.min(MIN_BUFFER_TO_START, remaining);
    if (cachedAhead >= required) {
      status = "playing";
      notify();
      playBlock(currentBlock);
    }
  }

  function countCachedAhead(fromIdx: number): number {
    let count = 0;
    for (let idx = fromIdx; idx < blocks.length; idx++) {
      if (audioCache.has(currentVariantKey(idx))) {
        count++;
      } else {
        break;
      }
    }
    return count;
  }

  // --- Derive block visual states ---

  function deriveBlockStates(): BlockVisualState[] {
    return blocks.map((_block, idx) => {
      const key = currentVariantKey(idx);
      if (audioCache.has(key)) return "cached";
      if (synthesisPromises.has(key)) return "synthesizing";
      return "pending";
    });
  }

  // --- Public API ---

  function play() {
    console.log("[Engine] play() called", { status, blocksLen: blocks.length, currentBlock, model, voiceSlug, documentId });
    if (status === "playing" || status === "buffering") return;
    if (!blocks.length) return;

    let startBlock = currentBlock;
    if (currentBlock === -1) {
      startBlock = findNextPlayable(0);
      if (startBlock < 0) return;
      currentBlock = startBlock;
      audioProgress = 0;
      blockStartTime = 0;
    } else if (isBlockSkipped(currentBlock)) {
      startBlock = findNextPlayable(currentBlock + 1);
      if (startBlock < 0) return;
      currentBlock = startBlock;
    }

    const cachedAhead = countCachedAhead(startBlock);
    const remaining = blocks.length - startBlock;
    const required = Math.min(MIN_BUFFER_TO_START, remaining);

    if (cachedAhead >= required) {
      status = "playing";
      notify();
      triggerPrefetch(startBlock + 1, BATCH_SIZE);
      playBlock(currentBlock);
    } else {
      status = "buffering";
      notify();
      triggerPrefetch(startBlock, BATCH_SIZE);
    }
  }

  function pause() {
    if (status !== "playing") return;
    deps.audioPlayer.pause();
    status = "stopped";
    isSynthesizingCurrent = false;
    notify();
  }

  function stop_() {
    deps.audioPlayer.stop();
    status = "stopped";
    isSynthesizingCurrent = false;


    if (documentId) {
      synthesizer.onCursorMove?.(documentId, currentBlock);
    }

    synthesizer.cancelAll();
    prefetchedUpTo = -1;
    synthesisPromises.clear();
    notify();
  }

  function skipForward() {
    if (!blocks.length || currentBlock >= blocks.length - 1) return;
    const next = findNextPlayable(currentBlock + 1);
    if (next < 0) return;
    deps.audioPlayer.stop();

    currentBlock = next;
    blockStartTime = calcProgressToBlock(next);
    audioProgress = blockStartTime;
    notify();
    if (status === "playing") playBlock(next);
  }

  function skipBack() {
    deps.audioPlayer.stop();

    if (currentBlock < 0 || !blocks.length) return;

    const prev = findPrevPlayable(currentBlock - 1);
    if (prev >= 0) {
      currentBlock = prev;
      blockStartTime = calcProgressToBlock(prev);
      audioProgress = blockStartTime;
      notify();
      if (status === "playing") playBlock(prev);
    } else {
      const first = findNextPlayable(0);
      if (first < 0) return;
      currentBlock = first;
      blockStartTime = 0;
      audioProgress = 0;
      notify();
      if (status === "playing") playBlock(first);
    }
  }

  function seekToBlock(blockIdx: number) {
    if (blockIdx < 0 || blockIdx >= blocks.length) return;
    deps.audioPlayer.stop();


    if (documentId) {
      synthesizer.onCursorMove?.(documentId, blockIdx);
    }

    currentBlock = blockIdx;
    blockStartTime = calcProgressToBlock(blockIdx);
    audioProgress = blockStartTime;
    notify();
    if (status === "playing") playBlock(blockIdx);
  }

  function setVoice(newModel: string, newVoiceSlug: string) {
    if (model === newModel && voiceSlug === newVoiceSlug) return;

    const wasActive = status === "playing" || status === "buffering";
    const oldModel = model;
    const oldVoice = voiceSlug;

    model = newModel;
    voiceSlug = newVoiceSlug;

    // Evict old voice audio and cancel pending synthesis
    for (const key of audioCache.keys()) {
      if (key.includes(`:${oldModel}:${oldVoice}`)) audioCache.delete(key);
    }

    synthesizer.cancelAll();
    synthesisPromises.clear();

    durationCorrections.clear();
    recalcTotalDuration();
    prefetchedUpTo = -1;

    if (wasActive && currentBlock >= 0) {
      deps.audioPlayer.stop();
  
      status = "buffering";
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

  function restorePosition(block: number, progressMs: number) {
    currentBlock = block;
    blockStartTime = progressMs;
    audioProgress = progressMs;
    notify();
  }

  function destroy() {
    deps.audioPlayer.stop();
    synthesizer.cancelAll();
    synthesisPromises.clear();
    audioCache.clear();
    listeners = [];
  }

  // --- Snapshot ---

  function getSnapshot(): PlaybackSnapshot {
    if (snapshot) return snapshot;
    snapshot = {
      status,
      currentBlock,
      isSynthesizingCurrent,
      blockStates: deriveBlockStates(),
      audioProgress,
      totalDuration,
    };
    return snapshot;
  }

  function subscribe(listener: () => void): () => void {
    listeners.push(listener);
    return () => { listeners = listeners.filter(l => l !== listener); };
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
    getBlockStartTime: () => blockStartTime,
    restorePosition,
    destroy,
  };
}

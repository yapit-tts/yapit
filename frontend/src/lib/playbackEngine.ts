import type { AudioPlayer } from "./audio";
import type { Section } from "./sectionIndex";
import { findSectionForBlock } from "./sectionIndex";
import { isServerSideModel, type ModelType } from "./voiceSelection";

// --- Types ---

export interface Block {
  id: number;
  idx: number;
  text: string;
  est_duration_ms: number;
}

export interface AudioBufferData {
  buffer: AudioBuffer;
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
  blockError: string | null;
}

export interface WSBlockStatusMessage {
  type: "status";
  document_id: string;
  block_idx: number;
  status: "queued" | "processing" | "cached" | "skipped" | "error";
  audio_url?: string;
  error?: string;
  model_slug?: string;
  voice_slug?: string;
}

export interface WSEvictedMessage {
  type: "evicted";
  document_id: string;
  block_indices: number[];
}

interface WSSynthesizeRequest {
  type: "synthesize";
  document_id: string;
  block_indices: number[];
  cursor: number;
  model: string;
  voice: string;
  synthesis_mode: "server";
}

interface WSCursorMoved {
  type: "cursor_moved";
  document_id: string;
  cursor: number;
}

// --- Configuration ---

const BATCH_SIZE = 8;
const REFILL_THRESHOLD = 8;
const MIN_BUFFER_TO_START = 2;
const EVICT_BEHIND = 20;
const SYNTHESIS_TIMEOUT_MS = 60_000;

// --- Variant key: `${blockIdx}:${model}:${voice}` ---

type VariantKey = string;

function variantKey(blockIdx: number, model: string, voice: string): VariantKey {
  return `${blockIdx}:${model}:${voice}`;
}

// --- Engine dependencies (injected for testability) ---

export interface PlaybackEngineDeps {
  audioPlayer: AudioPlayer;
  decodeAudio: (data: ArrayBuffer) => Promise<AudioBuffer>;
  fetchAudio: (url: string) => Promise<ArrayBuffer>;
  sendWS: (msg: WSSynthesizeRequest | WSCursorMoved) => void;
  checkWSConnected: () => boolean;
}

// null = cancelled (voice change, stop, eviction). Not an error — just "no audio, move on".
type SynthesisResult = AudioBufferData | null;

interface SynthesisResolver {
  resolve: (data: SynthesisResult) => void;
}

// --- Public interface ---

export interface PlaybackEngine {
  play(): void;
  pause(): void;
  stop(): void;
  skipForward(): void;
  skipBack(): void;
  seekToBlock(blockIdx: number): void;
  setVoice(model: ModelType, voiceSlug: string): void;
  setDocument(documentId: string, blocks: Block[]): void;
  setPlaybackSpeed(speed: number): void;
  setSections(sections: Section[], skippedSections: Set<string>): void;
  onBlockStatus(msg: WSBlockStatusMessage): void;
  onBlockEvicted(msg: WSEvictedMessage): void;
  onBrowserAudio(blockIdx: number, buffer: AudioBuffer, durationMs: number): void;
  cancelBrowserBlock(blockIdx: number): void;
  subscribe(listener: () => void): () => void;
  getSnapshot(): PlaybackSnapshot;
  getBlockStartTime(): number;
  restorePosition(block: number, progressMs: number): void;
  // Blocks pending browser-side synthesis (React layer drives these)
  getPendingBrowserBlocks(): number[];
  destroy(): void;
}

// --- Factory ---

export function createPlaybackEngine(deps: PlaybackEngineDeps): PlaybackEngine {
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
  const cachedVariants = new Set<VariantKey>();
  const wsBlockStates = new Map<number, { status: string; model_slug?: string; voice_slug?: string }>();

  const synthesisResolvers = new Map<VariantKey, SynthesisResolver>();
  const synthesisPromises = new Map<VariantKey, Promise<SynthesisResult>>();

  let blockError: string | null = null;

  let prefetchedUpTo = -1;

  let listeners: Array<() => void> = [];
  let snapshot: PlaybackSnapshot | null = null;

  // Wire progress updates from AudioPlayer into engine state
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
      ms += audio?.duration_ms ?? blocks[i].est_duration_ms ?? 0;
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

    const wsState = wsBlockStates.get(blockIdx);
    if (wsState?.status === "skipped") {
      advanceToNext();
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
    await deps.audioPlayer.load(audioData.buffer);
    await deps.audioPlayer.play();
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

  function synthesizeBlock(blockIdx: number): Promise<SynthesisResult> {
    const key = currentVariantKey(blockIdx);

    const cached = audioCache.get(key);
    if (cached) return Promise.resolve(cached);

    const existing = synthesisPromises.get(key);
    if (existing) return existing;

    const block = blocks[blockIdx];
    if (!block) return Promise.resolve(null);

    // Browser-side models: create resolver, React layer drives synthesis via onBrowserAudio
    if (!isServerSideModel(model as ModelType)) {
      const { promise } = createResolver(key);
      synthesisPromises.set(key, promise);
      return promise;
    }

    // Server mode: request via WS
    if (!deps.checkWSConnected()) return Promise.resolve(null);

    const { promise } = createResolver(key);
    synthesisPromises.set(key, promise);

    const ws = wsBlockStates.get(blockIdx);
    const alreadyRequestedForCurrentVoice = ws && ws.model_slug === model && ws.voice_slug === voiceSlug &&
      (ws.status === "queued" || ws.status === "processing" || ws.status === "cached");

    if (!alreadyRequestedForCurrentVoice) {
      deps.sendWS({
        type: "synthesize",
        document_id: documentId!,
        block_indices: [blockIdx],
        cursor: currentBlock,
        model: model,
        voice: voiceSlug,
        synthesis_mode: "server",
      });
    }

    return promise;
  }

  function createResolver(key: VariantKey): { promise: Promise<SynthesisResult> } {
    let rawResolve!: (data: SynthesisResult) => void;
    const promise = new Promise<SynthesisResult>((res) => { rawResolve = res; });

    const resolve = (data: SynthesisResult) => {
      clearTimeout(timer);
      synthesisResolvers.delete(key);
      synthesisPromises.delete(key);
      rawResolve(data);
    };

    const timer = setTimeout(() => {
      console.warn(`[Engine] Timeout waiting for block (key: ${key})`);
      resolve(null);
      notify();
    }, SYNTHESIS_TIMEOUT_MS);

    synthesisResolvers.set(key, { resolve });

    return { promise };
  }

  function resolveVariant(blockIdx: number, modelSlug: string, voice: string, audioData: AudioBufferData) {
    const key = variantKey(blockIdx, modelSlug, voice);
    audioCache.set(key, audioData);
    cachedVariants.add(key);

    const block = blocks[blockIdx];
    if (block) recordDurationCorrection(block, audioData.duration_ms);

    const resolver = synthesisResolvers.get(key);
    if (resolver) resolver.resolve(audioData);

    notify();
  }

  // --- Prefetch ---

  function triggerPrefetch(fromIdx: number, count: number) {
    if (!blocks.length || !documentId) return;
    const isServer = isServerSideModel(model as ModelType);
    const maxIdx = Math.min(fromIdx + count - 1, blocks.length - 1);

    if (isServer) {
      if (!deps.checkWSConnected()) return;

      const indicesToRequest: number[] = [];
      for (let idx = fromIdx; idx <= maxIdx; idx++) {
        const key = currentVariantKey(idx);
        if (audioCache.has(key) || synthesisPromises.has(key)) continue;

        const ws = wsBlockStates.get(idx);
        if (ws && ws.voice_slug === voiceSlug && ws.model_slug === model) {
          if (["cached", "queued", "processing", "skipped"].includes(ws.status)) continue;
        }
        indicesToRequest.push(idx);
      }

      if (indicesToRequest.length > 0) {
        deps.sendWS({
          type: "synthesize",
          document_id: documentId,
          block_indices: indicesToRequest,
          cursor: currentBlock,
          model: model,
          voice: voiceSlug,
          synthesis_mode: "server",
        });

        for (const idx of indicesToRequest) {
          const key = currentVariantKey(idx);
          if (!synthesisResolvers.has(key)) createResolver(key);
        }
      }
    } else {
      // Browser mode: create resolvers for React layer to fulfill via onBrowserAudio
      for (let idx = fromIdx; idx <= maxIdx; idx++) {
        const key = currentVariantKey(idx);
        if (audioCache.has(key) || synthesisPromises.has(key)) continue;
        createResolver(key);
      }
    }

    if (maxIdx > prefetchedUpTo) prefetchedUpTo = maxIdx;
  }

  function checkAndRefillBuffer() {
    if (!blocks.length) return;
    const isServer = isServerSideModel(model as ModelType);

    let readyAhead = 0;
    for (let idx = currentBlock + 1; idx < blocks.length; idx++) {
      const key = currentVariantKey(idx);
      if (audioCache.has(key) || synthesisPromises.has(key)) { readyAhead++; continue; }
      if (isServer) {
        const ws = wsBlockStates.get(idx);
        if (ws && ws.voice_slug === voiceSlug &&
            ["cached", "queued", "processing", "skipped"].includes(ws.status)) {
          readyAhead++;
          continue;
        }
      }
      break;
    }

    if (readyAhead >= REFILL_THRESHOLD) return;

    let firstUnready = currentBlock + 1;
    for (let idx = currentBlock + 1; idx < blocks.length; idx++) {
      const key = currentVariantKey(idx);
      if (audioCache.has(key) || synthesisPromises.has(key)) continue;
      if (isServer) {
        const ws = wsBlockStates.get(idx);
        if (ws && ws.voice_slug === voiceSlug &&
            ["cached", "queued", "processing", "skipped"].includes(ws.status)) continue;
      }
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

  // --- WS message handlers ---

  function onBlockStatus(msg: WSBlockStatusMessage) {
    if (!documentId || msg.document_id !== documentId) return;
    if (msg.model_slug && msg.voice_slug) {
      if (msg.model_slug !== model || msg.voice_slug !== voiceSlug) return;
    }

    wsBlockStates.set(msg.block_idx, {
      status: msg.status,
      model_slug: msg.model_slug,
      voice_slug: msg.voice_slug,
    });

    if (msg.status === "cached" && msg.audio_url) {
      const key = currentVariantKey(msg.block_idx);
      if (audioCache.has(key)) { notify(); return; }

      deps.fetchAudio(msg.audio_url).then(async (arrayBuffer) => {
        const audioBuffer = await deps.decodeAudio(arrayBuffer);
        const durationMs = Math.round(audioBuffer.duration * 1000);
        resolveVariant(msg.block_idx, msg.model_slug!, msg.voice_slug!, { buffer: audioBuffer, duration_ms: durationMs });
        checkBufferReady();
      }).catch((err) => {
        console.error(`[Engine] Failed to fetch audio for block ${msg.block_idx}:`, err);
        const resolver = synthesisResolvers.get(key);
        if (resolver) resolver.resolve(null);
      });
    } else if (msg.status === "error") {
      const key = currentVariantKey(msg.block_idx);
      blockError = msg.error || "Synthesis error";
      const resolver = synthesisResolvers.get(key);
      if (resolver) resolver.resolve(null);
    } else if (msg.status === "skipped") {
      const key = currentVariantKey(msg.block_idx);
      const resolver = synthesisResolvers.get(key);
      if (resolver) resolver.resolve(null);
    }

    notify();
  }

  function onBlockEvicted(msg: WSEvictedMessage) {
    if (!documentId || msg.document_id !== documentId) return;

    for (const idx of msg.block_indices) {
      wsBlockStates.delete(idx);
      const key = currentVariantKey(idx);
      const resolver = synthesisResolvers.get(key);
      if (resolver) resolver.resolve(null);
    }
    notify();
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
      const key = currentVariantKey(idx);
      const ws = wsBlockStates.get(idx);
      if (audioCache.has(key) || ws?.status === "skipped") {
        count++;
      } else {
        break;
      }
    }
    return count;
  }

  // --- Derive block visual states ---

  function deriveBlockStates(): BlockVisualState[] {
    const isServer = isServerSideModel(model as ModelType);
    return blocks.map((_block, idx) => {
      const key = currentVariantKey(idx);
      if (audioCache.has(key) || cachedVariants.has(key)) return "cached";
      if (isServer) {
        const ws = wsBlockStates.get(idx);
        if (ws && ws.model_slug === model && ws.voice_slug === voiceSlug) {
          if (ws.status === "cached") return "cached";
          if (ws.status === "queued" || ws.status === "processing") return "synthesizing";
        }
      }
      if (synthesisPromises.has(key)) return "synthesizing";
      return "pending";
    });
  }

  // --- Public API ---

  function play() {
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

    if (!isServerSideModel(model as ModelType)) {
      status = "playing";
      notify();
      playBlock(currentBlock);
      return;
    }

    // Server mode: start immediately if current block cached, else buffer
    const audio = getBlockAudio(startBlock);
    if (audio) {
      status = "playing";
      notify();
      triggerPrefetch(startBlock + 1, BATCH_SIZE);
      playBlock(currentBlock);
    } else {
      const cachedAhead = countCachedAhead(startBlock);
      const remaining = blocks.length - startBlock;
      const required = Math.min(MIN_BUFFER_TO_START, remaining);

      if (cachedAhead >= required) {
        status = "playing";
        notify();
        playBlock(currentBlock);
      } else {
        status = "buffering";
        notify();
        triggerPrefetch(startBlock, BATCH_SIZE);
      }
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

    if (documentId && isServerSideModel(model as ModelType)) {
      deps.sendWS({ type: "cursor_moved", document_id: documentId, cursor: currentBlock });
    }

    for (const [, resolver] of synthesisResolvers) {
      resolver.resolve(null);
    }
    prefetchedUpTo = -1;
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

    if (documentId && isServerSideModel(model as ModelType)) {
      deps.sendWS({ type: "cursor_moved", document_id: documentId, cursor: blockIdx });
    }

    currentBlock = blockIdx;
    blockStartTime = calcProgressToBlock(blockIdx);
    audioProgress = blockStartTime;
    notify();
    if (status === "playing") playBlock(blockIdx);
  }

  function setVoice(newModel: ModelType, newVoiceSlug: string) {
    if (model === newModel && voiceSlug === newVoiceSlug) return;

    const wasActive = status === "playing" || status === "buffering";
    const oldModel = model;
    const oldVoice = voiceSlug;

    model = newModel;
    voiceSlug = newVoiceSlug;

    // Evict old voice audio
    for (const key of audioCache.keys()) {
      if (key.includes(`:${oldModel}:${oldVoice}`)) audioCache.delete(key);
    }
    for (const key of cachedVariants) {
      if (key.includes(`:${oldModel}:${oldVoice}`)) cachedVariants.delete(key);
    }

    for (const [key, resolver] of synthesisResolvers) {
      if (key.includes(`:${oldModel}:${oldVoice}`)) {
        resolver.resolve(null);
      }
    }

    wsBlockStates.clear();
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

    for (const [, resolver] of synthesisResolvers) {
      resolver.resolve(null);
    }

    documentId = newDocumentId;
    blocks = newBlocks;
    status = "stopped";
    currentBlock = -1;
    isSynthesizingCurrent = false;
    audioProgress = 0;
    blockStartTime = 0;
    prefetchedUpTo = -1;

    audioCache.clear();
    cachedVariants.clear();
    wsBlockStates.clear();
    durationCorrections.clear();

    initialTotalEstimate = newBlocks.reduce((sum, b) => sum + (b.est_duration_ms || 0), 0);
    totalDuration = initialTotalEstimate;

    notify();
  }

  function setPlaybackSpeed(speed: number) {
    deps.audioPlayer.setTempo(speed);
  }

  function setSections_(newSections: Section[], newSkipped: Set<string>) {
    sections = newSections;
    skippedSections = newSkipped;
  }

  function onBrowserAudio(blockIdx: number, buffer: AudioBuffer, durationMs: number) {
    resolveVariant(blockIdx, model, voiceSlug, { buffer, duration_ms: durationMs });
    checkBufferReady();
  }

  function cancelBrowserBlock(blockIdx: number) {
    const key = currentVariantKey(blockIdx);
    const resolver = synthesisResolvers.get(key);
    if (resolver) resolver.resolve(null);
  }

  function getPendingBrowserBlocks(): number[] {
    if (isServerSideModel(model as ModelType)) return [];
    const pending: number[] = [];
    for (const [key] of synthesisResolvers) {
      const [idxStr, m, v] = key.split(":");
      if (m === model && v === voiceSlug) pending.push(parseInt(idxStr));
    }
    return pending;
  }

  function restorePosition(block: number, progressMs: number) {
    currentBlock = block;
    blockStartTime = progressMs;
    audioProgress = progressMs;
    notify();
  }

  function destroy() {
    deps.audioPlayer.stop();
    for (const [, resolver] of synthesisResolvers) {
      resolver.resolve(null);
    }
    audioCache.clear();
    cachedVariants.clear();
    wsBlockStates.clear();
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
      blockError,
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
    setSections: setSections_,
    onBlockStatus,
    onBlockEvicted,
    onBrowserAudio,
    cancelBrowserBlock,
    subscribe,
    getSnapshot,
    getBlockStartTime: () => blockStartTime,
    restorePosition,
    getPendingBrowserBlocks,
    destroy,
  };
}

import { describe, it, expect, vi, beforeEach, type Mock } from "vitest";
import {
  createPlaybackEngine,
  type PlaybackEngine,
  type PlaybackEngineDeps,
  type Block,
  type AudioBufferData,
  type WordTiming,
} from "./playbackEngine";
import type { Section } from "./sectionIndex";
import { StaleLoadError, UnplayableAudioError, type AudioPlayer } from "./audio";
import type { Synthesizer } from "./synthesizer";

// --- Test helpers ---

function makeBlocks(n: number): Block[] {
  return Array.from({ length: n }, (_, i) => ({
    idx: i,
    text: `Block ${i}`,
    est_duration_ms: 1000,
  }));
}

function makeSection(id: string, start: number, end: number): Section {
  return {
    id,
    title: id,
    level: 1,
    startBlockIdx: start,
    endBlockIdx: end,
    durationMs: (end - start + 1) * 1000,
    subsections: [],
  };
}

function mockAudioPlayer(): AudioPlayer {
  return {
    loadRawAudio: vi.fn().mockResolvedValue(1500),
    play: vi.fn().mockResolvedValue(undefined),
    pause: vi.fn(),
    stop: vi.fn(),
    setOnEnded: vi.fn(),
    setOnProgress: vi.fn(),
    setTempo: vi.fn(),
    setVolume: vi.fn(),
  } as unknown as AudioPlayer;
}

const FAKE_AUDIO: AudioBufferData = {
  rawAudio: new ArrayBuffer(8), mimeType: "audio/ogg", duration_ms: 1000,
};
/** A block whose length the server didn't report — known only once the element loads it. */
const fakeRawAudio = (wordTimings?: WordTiming[]): AudioBufferData =>
  ({ rawAudio: new ArrayBuffer(8), mimeType: "audio/ogg", duration_ms: 0, wordTimings });

type SynthesizeHandler = (blockIdx: number, text: string, documentId: string, model: string, voice: string) => Promise<AudioBufferData | null>;

/**
 * Mock synthesizer that lets tests control when synthesis resolves.
 * By default resolves immediately with FAKE_AUDIO. Set onSynthesize for custom behavior.
 */
function mockSynthesizer(): Synthesizer & { onSynthesize: SynthesizeHandler; cancelAll: Mock } {
  const synth: Synthesizer & { onSynthesize: SynthesizeHandler; cancelAll: Mock } = {
    onSynthesize: () => Promise.resolve(FAKE_AUDIO),
    synthesize(blockIdx, text, documentId, model, voice) {
      return synth.onSynthesize(blockIdx, text, documentId, model, voice);
    },
    cancelAll: vi.fn(),
    onCursorMove: vi.fn(),
    getError: () => null,
    isRecoverable: () => true,
    clearError: vi.fn(),
    destroy: vi.fn(),
  };
  return synth;
}

/**
 * Mock synthesizer that holds synthesis promises for manual resolution.
 */
function deferredSynthesizer() {
  const pending = new Map<number, { resolve: (data: AudioBufferData | null) => void }>();
  const synth = mockSynthesizer();
  synth.onSynthesize = (blockIdx) => new Promise((resolve) => {
    pending.set(blockIdx, { resolve });
  });
  return { synth, pending };
}

function makeDeps(overrides: Partial<PlaybackEngineDeps> = {}): PlaybackEngineDeps {
  return {
    audioPlayer: mockAudioPlayer(),
    synthesizer: mockSynthesizer(),
    ...overrides,
  };
}

// --- Tests ---

describe("createPlaybackEngine", () => {
  let deps: PlaybackEngineDeps;
  let engine: PlaybackEngine;

  beforeEach(() => {
    deps = makeDeps();
    engine = createPlaybackEngine(deps);
  });

  describe("initial state", () => {
    it("starts stopped with empty blocks", () => {
      const snap = engine.getSnapshot();
      expect(snap.status).toBe("stopped");
      expect(snap.currentBlock).toBe(-1);
      expect(snap.blockStates).toEqual([]);
      expect(snap.audioProgress).toBe(0);
      expect(snap.totalDuration).toBe(0);

    });
  });

  describe("setDocument", () => {
    it("sets total duration from block estimates", () => {
      engine.setDocument("doc-1", makeBlocks(5));
      expect(engine.getSnapshot().totalDuration).toBe(5000);
    });

    it("resets state on new document", () => {
      engine.setDocument("doc-1", makeBlocks(3));
      engine.setDocument("doc-2", makeBlocks(2));
      const snap = engine.getSnapshot();
      expect(snap.totalDuration).toBe(2000);
      expect(snap.blockStates).toHaveLength(2);
      expect(snap.currentBlock).toBe(-1);
    });
  });

  describe("subscribe / notify", () => {
    it("calls listeners on state changes", () => {
      const listener = vi.fn();
      engine.subscribe(listener);
      engine.setDocument("doc-1", makeBlocks(1));
      expect(listener).toHaveBeenCalled();
    });

    it("unsubscribe stops notifications", () => {
      const listener = vi.fn();
      const unsub = engine.subscribe(listener);
      unsub();
      engine.setDocument("doc-1", makeBlocks(1));
      expect(listener).not.toHaveBeenCalled();
    });

    it("caches snapshot until notify", () => {
      engine.setDocument("doc-1", makeBlocks(2));
      const a = engine.getSnapshot();
      const b = engine.getSnapshot();
      expect(a).toBe(b);
    });
  });

  describe("play / pause / stop", () => {
    it("does nothing with no blocks", () => {
      engine.play();
      expect(engine.getSnapshot().status).toBe("stopped");
    });

    it("enters buffering when no audio cached", () => {
      const { synth, pending } = deferredSynthesizer();
      const d = makeDeps({ synthesizer: synth });
      const e = createPlaybackEngine(d);

      e.setVoice("kokoro", "af_heart");
      e.setDocument("doc-1", makeBlocks(5));
      e.play();
      expect(e.getSnapshot().status).toBe("buffering");

      // Clean up deferred promises
      for (const [, p] of pending) p.resolve(null);
    });

    it("transitions to playing when buffer fills", async () => {
      const synth = mockSynthesizer();
      const d = makeDeps({ synthesizer: synth });
      const e = createPlaybackEngine(d);

      e.setVoice("kokoro", "af_heart");
      e.setDocument("doc-1", makeBlocks(3));
      e.play();

      // Synthesizer resolves immediately → buffer fills → playing
      await vi.waitFor(() => {
        expect(e.getSnapshot().status).toBe("playing");
      });
    });

    it("pause sets status to stopped", async () => {
      const synth = mockSynthesizer();
      const d = makeDeps({ synthesizer: synth });
      const e = createPlaybackEngine(d);

      e.setVoice("kokoro", "af_heart");
      e.setDocument("doc-1", makeBlocks(3));
      e.play();

      await vi.waitFor(() => {
        expect(e.getSnapshot().status).toBe("playing");
      });

      e.pause();
      expect(e.getSnapshot().status).toBe("stopped");
      expect(d.audioPlayer.pause).toHaveBeenCalled();
    });

    it("stop calls cancelAll on synthesizer", async () => {
      const synth = mockSynthesizer();
      const d = makeDeps({ synthesizer: synth });
      const e = createPlaybackEngine(d);

      e.setVoice("kokoro", "af_heart");
      e.setDocument("doc-1", makeBlocks(3));
      e.play();

      await vi.waitFor(() => {
        expect(e.getSnapshot().status).toBe("playing");
      });

      e.stop();
      expect(e.getSnapshot().status).toBe("stopped");
      expect(synth.cancelAll).toHaveBeenCalled();
      expect(d.audioPlayer.stop).toHaveBeenCalled();
    });
  });

  describe("block visual states", () => {
    it("shows synthesizing for pending blocks", () => {
      const { synth, pending } = deferredSynthesizer();
      const d = makeDeps({ synthesizer: synth });
      const e = createPlaybackEngine(d);

      e.setVoice("kokoro", "af_heart");
      e.setDocument("doc-1", makeBlocks(4));
      e.play();

      const states = e.getSnapshot().blockStates;
      // Blocks 0-7 (BATCH_SIZE=8) should be synthesizing, rest pending
      expect(states[0]).toBe("synthesizing");
      expect(states[1]).toBe("synthesizing");

      for (const [, p] of pending) p.resolve(null);
    });

    it("shows cached after synthesis resolves", async () => {
      const synth = mockSynthesizer();
      const d = makeDeps({ synthesizer: synth });
      const e = createPlaybackEngine(d);

      e.setVoice("kokoro", "af_heart");
      e.setDocument("doc-1", makeBlocks(4));
      e.play();

      await vi.waitFor(() => {
        expect(e.getSnapshot().blockStates[0]).toBe("cached");
      });
    });
  });

  describe("voice change cancellation", () => {
    it("calls cancelAll and enters buffering", () => {
      const { synth, pending } = deferredSynthesizer();
      const d = makeDeps({ synthesizer: synth });
      const e = createPlaybackEngine(d);

      e.setVoice("kokoro", "af_heart");
      e.setDocument("doc-1", makeBlocks(5));
      e.play();
      expect(e.getSnapshot().status).toBe("buffering");

      e.setVoice("kokoro", "am_fenrir");
      expect(e.getSnapshot().status).toBe("buffering");
      expect(synth.cancelAll).toHaveBeenCalled();

      for (const [, p] of pending) p.resolve(null);
    });

    it("evicts old voice audio from cache", async () => {
      const synth = mockSynthesizer();
      const d = makeDeps({ synthesizer: synth });
      const e = createPlaybackEngine(d);

      e.setVoice("kokoro", "af_heart");
      e.setDocument("doc-1", makeBlocks(3));
      e.play();

      await vi.waitFor(() => {
        expect(e.getSnapshot().blockStates[0]).toBe("cached");
      });

      e.setVoice("kokoro", "am_fenrir");
      expect(e.getSnapshot().blockStates[0]).toBe("synthesizing");
    });
  });

  describe("section skipping", () => {
    it("skips blocks in skipped sections during skipForward", async () => {
      const synth = mockSynthesizer();
      const d = makeDeps({ synthesizer: synth });
      const e = createPlaybackEngine(d);

      e.setVoice("kokoro", "af_heart");
      e.setDocument("doc-1", makeBlocks(10));

      const sections: Section[] = [
        makeSection("intro", 0, 2),
        makeSection("chapter1", 3, 6),
        makeSection("chapter2", 7, 9),
      ];
      e.setSections(sections, new Set(["chapter1"]));

      e.play();
      await vi.waitFor(() => {
        expect(e.getSnapshot().status).toBe("playing");
      });

      e.seekToBlock(2);
      expect(e.getSnapshot().currentBlock).toBe(2);

      e.skipForward();
      expect(e.getSnapshot().currentBlock).toBe(7);
    });
  });

  describe("seekToBlock", () => {
    it("updates currentBlock and progress", () => {
      engine.setVoice("kokoro", "af_heart");
      engine.setDocument("doc-1", makeBlocks(5));

      engine.seekToBlock(3);
      const snap = engine.getSnapshot();
      expect(snap.currentBlock).toBe(3);
      expect(snap.audioProgress).toBe(3000);
    });

    it("calls onCursorMove on synthesizer", () => {
      const synth = mockSynthesizer();
      const d = makeDeps({ synthesizer: synth });
      const e = createPlaybackEngine(d);

      e.setVoice("kokoro", "af_heart");
      e.setDocument("doc-1", makeBlocks(5));

      e.seekToBlock(2);
      expect(synth.onCursorMove).toHaveBeenCalledWith("doc-1", 2);
    });

    it("ignores out of range", () => {
      engine.setDocument("doc-1", makeBlocks(3));
      engine.seekToBlock(10);
      expect(engine.getSnapshot().currentBlock).toBe(-1);
      engine.seekToBlock(-1);
      expect(engine.getSnapshot().currentBlock).toBe(-1);
    });
  });

  describe("restorePosition", () => {
    it("sets block and computes progress from estimates", () => {
      engine.setDocument("doc-1", makeBlocks(5));
      engine.restorePosition(3);
      const snap = engine.getSnapshot();
      expect(snap.currentBlock).toBe(3);
      expect(snap.audioProgress).toBe(3000); // 3 blocks × 1000ms
    });
  });

  describe("skipBack", () => {
    it("goes to previous playable block", () => {
      engine.setVoice("kokoro", "af_heart");
      engine.setDocument("doc-1", makeBlocks(5));
      engine.seekToBlock(3);
      engine.skipBack();
      expect(engine.getSnapshot().currentBlock).toBe(2);
    });

    it("wraps to first playable when at start", () => {
      engine.setVoice("kokoro", "af_heart");
      engine.setDocument("doc-1", makeBlocks(5));
      engine.seekToBlock(0);
      engine.skipBack();
      expect(engine.getSnapshot().currentBlock).toBe(0);
    });
  });

  describe("duration correction", () => {
    it("adjusts totalDuration when actual audio duration differs from estimate", async () => {
      const synth = mockSynthesizer();
      synth.onSynthesize = () => Promise.resolve({
        rawAudio: new ArrayBuffer(8), mimeType: "audio/ogg", duration_ms: 1500,
      });
      const d = makeDeps({ synthesizer: synth });
      const e = createPlaybackEngine(d);

      e.setVoice("kokoro", "af_heart");
      e.setDocument("doc-1", makeBlocks(3)); // 3 * 1000ms = 3000ms
      expect(e.getSnapshot().totalDuration).toBe(3000);

      e.play();

      await vi.waitFor(() => {
        // Block 0 synthesized with 1500ms → correction of +500ms
        expect(e.getSnapshot().totalDuration).toBeGreaterThan(3000);
      });
    });
  });

  describe("server audio (compressed, duration known only at play time)", () => {
    function rawDeps(onSynthesize?: () => Promise<AudioBufferData | null>) {
      const synth = mockSynthesizer();
      synth.onSynthesize = onSynthesize ?? (() => Promise.resolve(fakeRawAudio()));
      return makeDeps({ synthesizer: synth });
    }

    it("plays compressed bytes directly and adopts the duration the element reports", async () => {
      const d = rawDeps();
      const e = createPlaybackEngine(d);
      e.setVoice("kokoro", "af_heart");
      e.setDocument("doc-1", makeBlocks(3)); // 3 * 1000ms estimate
      e.play();

      await vi.waitFor(() => {
        expect(d.audioPlayer.loadRawAudio).toHaveBeenCalled();
        // Block 0 reported 1500ms against a 1000ms estimate → +500ms
        expect(e.getSnapshot().totalDuration).toBe(3500);
      });
    });

    it("uses the server-reported duration before a block is played", async () => {
      const d = rawDeps(() => Promise.resolve({
        rawAudio: new ArrayBuffer(8), mimeType: "audio/ogg", duration_ms: 2500,
      }));
      // Never resolves: isolates the synthesis-time duration from the play-time correction.
      (d.audioPlayer.loadRawAudio as Mock).mockImplementation(() => new Promise<number>(() => {}));
      const e = createPlaybackEngine(d);
      e.setVoice("kokoro", "af_heart");
      e.setDocument("doc-1", makeBlocks(3));
      e.play();

      // All 3 blocks prefetch at 2500ms against a 1000ms estimate → +1500ms each
      await vi.waitFor(() => expect(e.getSnapshot().totalDuration).toBe(7500));
    });

    it("discards a duration that arrives after the cursor moved on", async () => {
      const d = rawDeps();
      const pendingLoads: Array<(ms: number) => void> = [];
      (d.audioPlayer.loadRawAudio as Mock).mockImplementation(
        () => new Promise<number>((resolve) => pendingLoads.push(resolve)),
      );
      const e = createPlaybackEngine(d);
      e.setVoice("kokoro", "af_heart");
      e.setDocument("doc-1", makeBlocks(5)); // 5000ms estimate
      e.play();

      await vi.waitFor(() => expect(pendingLoads).toHaveLength(1));
      e.seekToBlock(2);
      await vi.waitFor(() => expect(pendingLoads).toHaveLength(2));

      // Block 0's load finally resolves — it belongs to a block we already left.
      pendingLoads[0](9999);
      await Promise.resolve();
      expect(e.getSnapshot().totalDuration).toBe(5000);

      // The current block's own load still counts.
      pendingLoads[1](2000);
      await vi.waitFor(() => expect(e.getSnapshot().totalDuration).toBe(6000));
    });

    it("stays on the seeked block when a superseded load rejects", async () => {
      const d = rawDeps();
      const rejects: Array<(err: Error) => void> = [];
      (d.audioPlayer.loadRawAudio as Mock).mockImplementation(
        () => new Promise<number>((_, reject) => rejects.push(reject)),
      );
      const e = createPlaybackEngine(d);
      e.setVoice("kokoro", "af_heart");
      e.setDocument("doc-1", makeBlocks(30));
      e.play();

      await vi.waitFor(() => expect(rejects).toHaveLength(1));
      e.seekToBlock(20);
      expect(e.getSnapshot().currentBlock).toBe(20);

      // Block 0's abandoned load finally gives up — it must not move the cursor.
      rejects[0](new StaleLoadError("superseded"));
      await new Promise((r) => setTimeout(r, 0));
      expect(e.getSnapshot().currentBlock).toBe(20);
    });

    it("stops rather than skipping every block when audio is unplayable", async () => {
      const d = rawDeps();
      (d.audioPlayer.loadRawAudio as Mock).mockRejectedValue(
        new UnplayableAudioError("unsupported container"),
      );
      const e = createPlaybackEngine(d);
      e.setVoice("kokoro", "af_heart");
      e.setDocument("doc-1", makeBlocks(10));
      e.play();

      await vi.waitFor(() => expect(e.getSnapshot().status).toBe("stopped"));
      // Not a silent fast-forward through the document.
      expect(e.getSnapshot().currentBlock).toBe(0);
      // And the user is told why, rather than play doing nothing.
      expect(e.getSnapshot().playbackError).toMatch(/can't play/i);
    });

    it("clears the playback error when the user presses play again", async () => {
      const d = rawDeps();
      (d.audioPlayer.loadRawAudio as Mock).mockRejectedValue(new UnplayableAudioError("nope"));
      const e = createPlaybackEngine(d);
      e.setVoice("kokoro", "af_heart");
      e.setDocument("doc-1", makeBlocks(3));
      e.play();
      await vi.waitFor(() => expect(e.getSnapshot().playbackError).toBeTruthy());

      (d.audioPlayer.loadRawAudio as Mock).mockResolvedValue(1500);
      e.play();
      expect(e.getSnapshot().playbackError).toBeNull();
    });
  });

  describe("setPlaybackSpeed", () => {
    it("delegates to audioPlayer", () => {
      engine.setPlaybackSpeed(1.5);
      expect(deps.audioPlayer.setTempo).toHaveBeenCalledWith(1.5);
    });
  });

  describe("destroy", () => {
    it("stops audio and clears listeners", () => {
      const listener = vi.fn();
      engine.subscribe(listener);
      engine.destroy();
      expect(deps.audioPlayer.stop).toHaveBeenCalled();
      listener.mockClear();
      engine.setDocument("doc-1", makeBlocks(1));
      expect(listener).not.toHaveBeenCalled();
    });
  });

  describe("synthesis error handling", () => {
    it("stops immediately when synthesizer has an unrecoverable error (buffering)", async () => {
      const synth = mockSynthesizer();
      let errorMsg: string | null = null;
      synth.getError = () => errorMsg;
      synth.isRecoverable = () => false;
      synth.onSynthesize = () => {
        errorMsg = "Usage limit exceeded for premium_voice: limit 0, used 0, requested 16, remaining 0";
        return Promise.resolve(null);
      };

      const d = makeDeps({ synthesizer: synth });
      const e = createPlaybackEngine(d);

      e.setVoice("openai-tts", "alex");
      e.setDocument("doc-1", makeBlocks(5));
      e.play();
      expect(e.getSnapshot().status).toBe("buffering");

      await vi.waitFor(() => {
        expect(e.getSnapshot().status).toBe("stopped");
      });
    });

    it("stops when reaching an unrecoverable error block during playback", async () => {
      const synth = mockSynthesizer();
      let errorMsg: string | null = null;
      let callCount = 0;
      synth.getError = () => errorMsg;
      synth.isRecoverable = () => errorMsg === null;
      synth.onSynthesize = () => {
        callCount++;
        if (callCount > 2) {
          errorMsg = "Usage limit exceeded";
          return Promise.resolve(null);
        }
        return Promise.resolve(FAKE_AUDIO);
      };

      const d = makeDeps({ synthesizer: synth });
      const e = createPlaybackEngine(d);

      e.setVoice("openai-tts", "alex");
      e.setDocument("doc-1", makeBlocks(10));
      e.play();

      await vi.waitFor(() => {
        expect(e.getSnapshot().status).toBe("playing");
      });

      // Advance through cached blocks: block 0 → block 1 → block 2 (error)
      const setOnEnded = d.audioPlayer.setOnEnded as Mock;
      let onEnded = setOnEnded.mock.calls.at(-1)?.[0];
      onEnded(); // Block 0 finishes → plays block 1
      await vi.waitFor(() => {
        expect(e.getSnapshot().currentBlock).toBe(1);
      });

      onEnded = setOnEnded.mock.calls.at(-1)?.[0];
      onEnded(); // Block 1 finishes → tries block 2 (fails with error)

      await vi.waitFor(() => {
        expect(e.getSnapshot().status).toBe("stopped");
      });
    });

    it("advances past transient null (no getError) instead of stopping", async () => {
      const synth = mockSynthesizer();
      // All blocks succeed — getError always null. The getError() check
      // must not interfere with normal null results (e.g. from cancellation).
      synth.getError = () => null;

      const d = makeDeps({ synthesizer: synth });
      const e = createPlaybackEngine(d);

      e.setVoice("kokoro", "af_heart");
      e.setDocument("doc-1", makeBlocks(5));
      e.play();

      await vi.waitFor(() => {
        expect(e.getSnapshot().status).toBe("playing");
      });

      // Advance block 0 → block 1 via onEnded (normal flow, no error)
      const setOnEnded = d.audioPlayer.setOnEnded as Mock;
      const onEnded = setOnEnded.mock.calls.at(-1)?.[0];
      onEnded();

      await vi.waitFor(() => {
        expect(e.getSnapshot().currentBlock).toBe(1);
        expect(e.getSnapshot().status).toBe("playing");
      });
    });

    it("advances past recoverable error during playback instead of stopping", async () => {
      const synth = mockSynthesizer();
      let errorMsg: string | null = null;
      synth.getError = () => errorMsg;
      synth.isRecoverable = () => true;
      // Block 1 always fails (recoverable), all others succeed
      synth.onSynthesize = (blockIdx) => {
        if (blockIdx === 1) {
          errorMsg = "[Errno 12] Cannot allocate memory";
          return Promise.resolve(null);
        }
        errorMsg = null;
        return Promise.resolve(FAKE_AUDIO);
      };

      const d = makeDeps({ synthesizer: synth });
      const e = createPlaybackEngine(d);

      e.setVoice("kokoro", "af_heart");
      e.setDocument("doc-1", makeBlocks(5));
      e.play();

      await vi.waitFor(() => {
        expect(e.getSnapshot().status).toBe("playing");
      });

      // Block 0 finishes → tries block 1 (recoverable error) → should advance to block 2
      const setOnEnded = d.audioPlayer.setOnEnded as Mock;
      const onEnded = setOnEnded.mock.calls.at(-1)?.[0];
      onEnded();

      await vi.waitFor(() => {
        expect(e.getSnapshot().currentBlock).toBe(2);
        expect(e.getSnapshot().status).toBe("playing");
      });
    });

    it("transitions from buffering to playing when first block is skipped", async () => {
      const synth = mockSynthesizer();
      let callCount = 0;
      // First block returns null (skipped), rest succeed
      synth.onSynthesize = () => {
        callCount++;
        if (callCount === 1) return Promise.resolve(null);
        return Promise.resolve(FAKE_AUDIO);
      };

      const d = makeDeps({ synthesizer: synth });
      const e = createPlaybackEngine(d);

      e.setVoice("openai-tts", "blake");
      e.setDocument("doc-1", makeBlocks(5));
      e.play();
      expect(e.getSnapshot().status).toBe("buffering");

      // Block 0 resolves null (skipped) → resolvedEmpty. Block 1 resolves with audio.
      // checkBufferReady should count block 0 (resolvedEmpty) + block 1 (cached) → buffer ready.
      await vi.waitFor(() => {
        expect(e.getSnapshot().status).toBe("playing");
      });
    });
  });
});

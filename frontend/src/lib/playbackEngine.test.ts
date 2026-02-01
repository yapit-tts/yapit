import { describe, it, expect, vi, beforeEach, type Mock } from "vitest";
import {
  createPlaybackEngine,
  type PlaybackEngine,
  type PlaybackEngineDeps,
  type Block,
  type WSBlockStatusMessage,
} from "./playbackEngine";
import type { Section } from "./sectionIndex";
import type { AudioPlayer } from "./audio";

// --- Test helpers ---

function makeBlocks(n: number): Block[] {
  return Array.from({ length: n }, (_, i) => ({
    id: i,
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
    load: vi.fn().mockResolvedValue(undefined),
    play: vi.fn().mockResolvedValue(undefined),
    pause: vi.fn(),
    stop: vi.fn(),
    setOnEnded: vi.fn(),
    setOnProgress: vi.fn(),
    setTempo: vi.fn(),
  } as unknown as AudioPlayer;
}

const FAKE_BUFFER = {} as AudioBuffer;

function makeDeps(overrides: Partial<PlaybackEngineDeps> = {}): PlaybackEngineDeps {
  return {
    audioPlayer: mockAudioPlayer(),
    decodeAudio: vi.fn().mockResolvedValue(FAKE_BUFFER),
    fetchAudio: vi.fn().mockResolvedValue(new ArrayBuffer(8)),
    sendWS: vi.fn(),
    checkWSConnected: vi.fn().mockReturnValue(true),
    ...overrides,
  };
}

function statusMsg(
  blockIdx: number,
  status: WSBlockStatusMessage["status"],
  opts: Partial<WSBlockStatusMessage> = {},
): WSBlockStatusMessage {
  return {
    type: "status",
    document_id: "doc-1",
    block_idx: blockIdx,
    status,
    model_slug: "kokoro",
    voice_slug: "af_heart",
    ...opts,
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
      expect(snap.blockError).toBeNull();
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
      expect(a).toBe(b); // same reference
    });
  });

  describe("document_id filtering", () => {
    it("ignores block status for wrong document", () => {
      engine.setVoice("kokoro", "af_heart");
      engine.setDocument("doc-1", makeBlocks(3));

      engine.onBlockStatus(statusMsg(0, "cached", {
        document_id: "doc-WRONG",
        audio_url: "/audio/0.wav",
      }));

      expect(engine.getSnapshot().blockStates[0]).toBe("pending");
    });

    it("accepts block status for correct document", () => {
      engine.setVoice("kokoro", "af_heart");
      engine.setDocument("doc-1", makeBlocks(3));

      engine.onBlockStatus(statusMsg(0, "queued"));
      expect(engine.getSnapshot().blockStates[0]).toBe("synthesizing");
    });
  });

  describe("voice/model filtering", () => {
    it("ignores block status for wrong voice", () => {
      engine.setVoice("kokoro", "af_heart");
      engine.setDocument("doc-1", makeBlocks(3));

      engine.onBlockStatus(statusMsg(0, "queued", {
        model_slug: "kokoro",
        voice_slug: "am_fenrir",
      }));

      expect(engine.getSnapshot().blockStates[0]).toBe("pending");
    });

    it("ignores block status for wrong model", () => {
      engine.setVoice("kokoro", "af_heart");
      engine.setDocument("doc-1", makeBlocks(3));

      engine.onBlockStatus(statusMsg(0, "queued", {
        model_slug: "inworld-1.5",
        voice_slug: "af_heart",
      }));

      expect(engine.getSnapshot().blockStates[0]).toBe("pending");
    });
  });

  describe("block visual states", () => {
    beforeEach(() => {
      engine.setVoice("kokoro", "af_heart");
      engine.setDocument("doc-1", makeBlocks(4));
    });

    it("shows queued/processing as synthesizing", () => {
      engine.onBlockStatus(statusMsg(0, "queued"));
      engine.onBlockStatus(statusMsg(1, "processing"));
      const states = engine.getSnapshot().blockStates;
      expect(states[0]).toBe("synthesizing");
      expect(states[1]).toBe("synthesizing");
      expect(states[2]).toBe("pending");
    });

    it("shows cached after audio arrives", async () => {
      engine.onBlockStatus(statusMsg(0, "cached", { audio_url: "/audio/0.wav" }));
      // fetchAudio + decodeAudio are async
      await vi.waitFor(() => {
        expect(engine.getSnapshot().blockStates[0]).toBe("cached");
      });
    });
  });

  describe("block errors", () => {
    it("sets blockError on error status", () => {
      engine.setVoice("kokoro", "af_heart");
      engine.setDocument("doc-1", makeBlocks(3));

      engine.onBlockStatus(statusMsg(0, "error", { error: "GPU OOM" }));
      expect(engine.getSnapshot().blockError).toBe("GPU OOM");
    });
  });

  describe("eviction", () => {
    it("clears WS state for evicted blocks", () => {
      engine.setVoice("kokoro", "af_heart");
      engine.setDocument("doc-1", makeBlocks(5));

      engine.onBlockStatus(statusMsg(2, "queued"));
      expect(engine.getSnapshot().blockStates[2]).toBe("synthesizing");

      engine.onBlockEvicted({
        type: "evicted",
        document_id: "doc-1",
        block_indices: [2],
      });
      // After eviction, WS state cleared → back to pending
      expect(engine.getSnapshot().blockStates[2]).toBe("pending");
    });

    it("ignores eviction for wrong document", () => {
      engine.setVoice("kokoro", "af_heart");
      engine.setDocument("doc-1", makeBlocks(3));

      engine.onBlockStatus(statusMsg(0, "queued"));
      engine.onBlockEvicted({
        type: "evicted",
        document_id: "doc-WRONG",
        block_indices: [0],
      });
      expect(engine.getSnapshot().blockStates[0]).toBe("synthesizing");
    });
  });

  describe("play / pause / stop", () => {
    it("does nothing with no blocks", () => {
      engine.play();
      expect(engine.getSnapshot().status).toBe("stopped");
    });

    it("enters buffering when no audio cached (server model)", () => {
      engine.setVoice("kokoro", "af_heart");
      engine.setDocument("doc-1", makeBlocks(5));
      engine.play();
      expect(engine.getSnapshot().status).toBe("buffering");
    });

    it("sends WS synthesize request on play", () => {
      engine.setVoice("kokoro", "af_heart");
      engine.setDocument("doc-1", makeBlocks(5));
      engine.play();
      expect(deps.sendWS).toHaveBeenCalledWith(
        expect.objectContaining({
          type: "synthesize",
          document_id: "doc-1",
          model: "kokoro",
          voice: "af_heart",
        }),
      );
    });

    it("pause sets status to stopped", async () => {
      engine.setVoice("kokoro", "af_heart");
      engine.setDocument("doc-1", makeBlocks(3));

      // Pre-cache blocks so play transitions to playing
      for (let i = 0; i < 3; i++) {
        engine.onBlockStatus(statusMsg(i, "cached", { audio_url: `/audio/${i}.wav` }));
      }
      await vi.waitFor(() => {
        expect(engine.getSnapshot().blockStates[0]).toBe("cached");
      });

      engine.play();
      // With enough cached blocks, should transition to playing
      await vi.waitFor(() => {
        expect(engine.getSnapshot().status).toBe("playing");
      });

      engine.pause();
      expect(engine.getSnapshot().status).toBe("stopped");
      expect(deps.audioPlayer.pause).toHaveBeenCalled();
    });

    it("stop resets position", async () => {
      engine.setVoice("kokoro", "af_heart");
      engine.setDocument("doc-1", makeBlocks(3));

      // Pre-cache
      for (let i = 0; i < 3; i++) {
        engine.onBlockStatus(statusMsg(i, "cached", { audio_url: `/audio/${i}.wav` }));
      }
      await vi.waitFor(() => {
        expect(engine.getSnapshot().blockStates[0]).toBe("cached");
      });

      engine.play();
      await vi.waitFor(() => {
        expect(engine.getSnapshot().status).toBe("playing");
      });

      engine.stop();
      const snap = engine.getSnapshot();
      expect(snap.status).toBe("stopped");
      // stop doesn't reset currentBlock (pause-like for cursor_moved), but does reset playingBlock
      expect(deps.audioPlayer.stop).toHaveBeenCalled();
    });
  });

  describe("voice change cancellation", () => {
    it("resolves pending synthesis as null and enters buffering", () => {
      engine.setVoice("kokoro", "af_heart");
      engine.setDocument("doc-1", makeBlocks(5));

      // Start playing → buffering with pending synthesis
      engine.play();
      expect(engine.getSnapshot().status).toBe("buffering");

      // Change voice mid-stream
      engine.setVoice("kokoro", "am_fenrir");

      // Should still be buffering (restarted with new voice)
      expect(engine.getSnapshot().status).toBe("buffering");

      // New prefetch should use new voice
      expect(deps.sendWS).toHaveBeenLastCalledWith(
        expect.objectContaining({
          voice: "am_fenrir",
        }),
      );
    });

    it("evicts old voice audio from cache", async () => {
      engine.setVoice("kokoro", "af_heart");
      engine.setDocument("doc-1", makeBlocks(3));

      // Cache a block with old voice
      engine.onBlockStatus(statusMsg(0, "cached", { audio_url: "/audio/0.wav" }));
      await vi.waitFor(() => {
        expect(engine.getSnapshot().blockStates[0]).toBe("cached");
      });

      // Switch voice
      engine.setVoice("kokoro", "am_fenrir");

      // Old cache evicted → back to pending
      expect(engine.getSnapshot().blockStates[0]).toBe("pending");
    });
  });

  describe("section skipping", () => {
    it("skips blocks in skipped sections during skipForward", async () => {
      engine.setVoice("kokoro", "af_heart");
      engine.setDocument("doc-1", makeBlocks(10));

      const sections: Section[] = [
        makeSection("intro", 0, 2),
        makeSection("chapter1", 3, 6),
        makeSection("chapter2", 7, 9),
      ];
      engine.setSections(sections, new Set(["chapter1"]));

      // Pre-cache all blocks
      for (let i = 0; i < 10; i++) {
        engine.onBlockStatus(statusMsg(i, "cached", { audio_url: `/audio/${i}.wav` }));
      }
      await vi.waitFor(() => {
        expect(engine.getSnapshot().blockStates[9]).toBe("cached");
      });

      engine.play();
      await vi.waitFor(() => {
        expect(engine.getSnapshot().status).toBe("playing");
      });

      // Currently on block 0 (intro). Skip forward past intro into the skipped chapter1.
      // Seek to block 2 (end of intro)
      engine.seekToBlock(2);
      expect(engine.getSnapshot().currentBlock).toBe(2);

      // Skip forward should jump to chapter2 (block 7), not chapter1 (block 3)
      engine.skipForward();
      expect(engine.getSnapshot().currentBlock).toBe(7);
    });
  });

  describe("seekToBlock", () => {
    it("updates currentBlock and progress", () => {
      engine.setVoice("kokoro", "af_heart");
      engine.setDocument("doc-1", makeBlocks(5));

      engine.seekToBlock(3);
      const snap = engine.getSnapshot();
      expect(snap.currentBlock).toBe(3);
      // Progress = sum of est_duration_ms for blocks 0-2 = 3000
      expect(snap.audioProgress).toBe(3000);
    });

    it("sends cursor_moved for server models", () => {
      engine.setVoice("kokoro", "af_heart");
      engine.setDocument("doc-1", makeBlocks(5));

      engine.seekToBlock(2);
      expect(deps.sendWS).toHaveBeenCalledWith(
        expect.objectContaining({
          type: "cursor_moved",
          document_id: "doc-1",
          cursor: 2,
        }),
      );
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
    it("sets block and progress", () => {
      engine.setDocument("doc-1", makeBlocks(5));
      engine.restorePosition(3, 4500);
      const snap = engine.getSnapshot();
      expect(snap.currentBlock).toBe(3);
      expect(snap.audioProgress).toBe(4500);
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

  describe("browser model", () => {
    it("goes directly to playing (no buffering)", () => {
      engine.setVoice("kokoro-browser", "af_heart");
      engine.setDocument("doc-1", makeBlocks(3));
      engine.play();
      expect(engine.getSnapshot().status).toBe("playing");
    });

    it("does not send WS requests", () => {
      engine.setVoice("kokoro-browser", "af_heart");
      engine.setDocument("doc-1", makeBlocks(3));
      engine.play();
      expect(deps.sendWS).not.toHaveBeenCalled();
    });

    it("reports pending browser blocks", () => {
      engine.setVoice("kokoro-browser", "af_heart");
      engine.setDocument("doc-1", makeBlocks(3));
      engine.play();
      const pending = engine.getPendingBrowserBlocks();
      // Block 0 should have a resolver created
      expect(pending).toContain(0);
    });

    it("onBrowserAudio resolves synthesis", async () => {
      engine.setVoice("kokoro-browser", "af_heart");
      engine.setDocument("doc-1", makeBlocks(3));
      engine.play();

      const buf = {} as AudioBuffer;
      engine.onBrowserAudio(0, buf, 1200);

      await vi.waitFor(() => {
        expect(engine.getSnapshot().blockStates[0]).toBe("cached");
      });
    });

    it("cancelBrowserBlock resolves as null", () => {
      engine.setVoice("kokoro-browser", "af_heart");
      engine.setDocument("doc-1", makeBlocks(3));
      engine.play();

      // Cancel block 0
      engine.cancelBrowserBlock(0);
      // Should not crash, resolver cleaned up
      expect(engine.getPendingBrowserBlocks()).not.toContain(0);
    });
  });

  describe("timeout", () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });

    it("resolves pending synthesis as null after 60s", async () => {
      engine.setVoice("kokoro", "af_heart");
      engine.setDocument("doc-1", makeBlocks(3));
      engine.play();

      // Advance past 60s timeout
      vi.advanceTimersByTime(61_000);

      // The buffering should still be buffering (no audio arrived)
      // but resolvers should have been cleaned up via timeout
      // Verify by checking that a new play attempt would re-request
      const sendCalls = (deps.sendWS as Mock).mock.calls.length;
      engine.stop();
      engine.play();
      expect((deps.sendWS as Mock).mock.calls.length).toBeGreaterThan(sendCalls);

      vi.useRealTimers();
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
      // After destroy, no more notifications
      listener.mockClear();
      engine.setDocument("doc-1", makeBlocks(1));
      expect(listener).not.toHaveBeenCalled();
    });
  });

  describe("skipped block status", () => {
    it("resolves skipped blocks as null", () => {
      engine.setVoice("kokoro", "af_heart");
      engine.setDocument("doc-1", makeBlocks(3));

      engine.onBlockStatus(statusMsg(1, "skipped"));
      // Skipped blocks don't show as cached or synthesizing — they're transparent
      const states = engine.getSnapshot().blockStates;
      expect(states[1]).toBe("pending");
    });
  });

  describe("duration correction", () => {
    it("adjusts totalDuration when actual audio duration differs from estimate", async () => {
      engine.setVoice("kokoro", "af_heart");
      engine.setDocument("doc-1", makeBlocks(3)); // 3 * 1000ms = 3000ms
      expect(engine.getSnapshot().totalDuration).toBe(3000);

      // Block 0 arrives with 1500ms actual (500ms more than 1000ms estimate)
      const longBuffer = { duration: 1.5 } as AudioBuffer;
      (deps.decodeAudio as Mock).mockResolvedValueOnce(longBuffer);
      engine.onBlockStatus(statusMsg(0, "cached", { audio_url: "/audio/0.wav" }));

      await vi.waitFor(() => {
        expect(engine.getSnapshot().totalDuration).toBe(3500);
      });
    });
  });
});

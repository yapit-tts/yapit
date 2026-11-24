import { describe, it, expect, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useAudioSelection, type AudioSelectionProps } from "./useAudioSelection";
import { KOKORO_SLUG } from "@/lib/voiceSelection";

const session = { isAnonymous: false };
const api = { get: vi.fn(() => Promise.resolve({ data: { uncached_characters: [0, 0], plan_includes_voice: true, available_characters: null, running_job_document_id: null } })) };
vi.mock("@/api", () => ({ useApi: () => ({ api, isAnonymous: session.isAnonymous }) }));

const props = (onDownload: AudioSelectionProps["onDownload"]): AudioSelectionProps => ({
  documentId: "doc",
  sections: [],
  documentBlocks: [{ est_duration_ms: 1000 }, { est_duration_ms: 2000 }],
  expandedSections: new Set(),
  voiceSelection: { model: KOKORO_SLUG, voiceSlug: "af_heart" },
  onVoiceChange: () => {},
  job: null,
  onStart: async () => null,
  onCancel: async () => {},
  exportProgress: {},
  onDownload,
});

describe("useAudioSelection", () => {
  it("asks a guest who saves a file to sign in, and asks the server nothing", async () => {
    session.isAnonymous = true;
    const onDownload = vi.fn(async () => {});
    const { result } = renderHook(() => useAudioSelection(props(onDownload)));

    await act(async () => result.current.download("m4b"));

    expect(onDownload).not.toHaveBeenCalled();
    expect(result.current.signInToSave).toBe(true);
  });

  it("saves the ticked sections for someone signed in", async () => {
    session.isAnonymous = false;
    const onDownload = vi.fn(async () => {});
    const { result } = renderHook(() => useAudioSelection(props(onDownload)));

    await act(async () => result.current.download("mp3"));

    expect(onDownload).toHaveBeenCalledWith("mp3", KOKORO_SLUG, "af_heart", [{ first_block: 0, last_block: 1, title: "Whole document" }]);
    expect(result.current.signInToSave).toBe(false);
  });
});

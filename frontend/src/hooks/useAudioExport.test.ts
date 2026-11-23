import { describe, it, expect, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useAudioExport } from "./useAudioExport";
import type { WSAudioExportMessage } from "@/lib/audioJob";

const api = { post: vi.fn(), get: vi.fn() };
vi.mock("@/api", () => ({ useApi: () => ({ api }) }));

const message = (key: string, status: WSAudioExportMessage["status"], progress: number | null): WSAudioExportMessage => ({
  type: "audio_export", document_id: "doc", key, format: "m4b", status, progress, error: null,
});

describe("useAudioExport", () => {
  it("shows how far a save's build is, then how far its download is, and nothing once the file is saved", async () => {
    api.post.mockResolvedValue({ data: { key: "asked-for", format: "m4b", status: "building", progress: 0.25, error: null } });
    let downloadProgress!: (event: { loaded: number; total?: number }) => void;
    let arrive!: (response: { data: Blob }) => void;
    api.get.mockImplementation((_url: string, config: { onDownloadProgress: typeof downloadProgress }) => {
      downloadProgress = config.onDownloadProgress;
      return new Promise(resolve => { arrive = resolve; });
    });
    URL.createObjectURL = vi.fn(() => "blob:file");
    URL.revokeObjectURL = vi.fn();
    const clicked = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const { result } = renderHook(() => useAudioExport("doc", "A Book"));

    await act(() => result.current.download("m4b", "kokoro", "af_heart", [{ first_block: 0, last_block: 5, title: "All" }]));
    expect(result.current.progress).toEqual({ m4b: { phase: "building", fraction: 0.25 } });

    act(() => result.current.receive(message("another-selection", "building", 0.9)));
    expect(result.current.progress).toEqual({ m4b: { phase: "building", fraction: 0.25 } });
    act(() => result.current.receive(message("asked-for", "building", 0.5)));
    expect(result.current.progress).toEqual({ m4b: { phase: "building", fraction: 0.5 } });

    act(() => result.current.receive(message("asked-for", "ready", null)));
    expect(result.current.progress).toEqual({ m4b: { phase: "downloading", fraction: 0 } });
    act(() => downloadProgress({ loaded: 30, total: 120 }));
    expect(result.current.progress).toEqual({ m4b: { phase: "downloading", fraction: 0.25 } });

    await act(async () => arrive({ data: new Blob() }));
    expect(clicked).toHaveBeenCalledOnce();
    expect(result.current.progress).toEqual({});
  });
});

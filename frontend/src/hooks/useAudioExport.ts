import { useCallback, useRef, useState } from "react";
import { AxiosError } from "axios";
import { useApi } from "@/api";
import type { AudioExportState, BlockRange, ExportFormat, WSAudioExportMessage } from "@/lib/audioJob";

/** Per format: how far its file is on the way, built by the server and then downloaded, or why it last failed. */
export type ExportProgress = Partial<Record<ExportFormat,
  | { phase: "building" | "downloading"; fraction: number }
  | { phase: "failed"; error: string }
>>;

export interface UseAudioExportReturn {
  progress: ExportProgress;
  /** Takes an `audio_export` message from the WebSocket: a file this tab waits on is downloaded once built. */
  receive: (message: WSAudioExportMessage) => void;
  /** Asks for the file; it downloads now if stored, or once the gateway says it is built. */
  download: (format: ExportFormat, model: string, voice: string, ranges: BlockRange[]) => Promise<void>;
  /** Asks again for each file still awaited, for a socket that reconnected and may have missed its message. */
  resume: () => void;
}

export function useAudioExport(documentId: string | undefined, documentTitle: string | undefined): UseAudioExportReturn {
  const { api } = useApi();
  const [tracked, setTracked] = useState<{ documentId: string | undefined; progress: ExportProgress }>({ documentId, progress: {} });
  const progress = tracked.documentId === documentId ? tracked.progress : {};
  const setProgress = useCallback((update: (prev: ExportProgress) => ExportProgress) => {
    setTracked(prev => ({ documentId, progress: update(prev.documentId === documentId ? prev.progress : {}) }));
  }, [documentId]);
  // The key each format's build was answered with, so a message for an older selection is ignored
  const awaitedKeys = useRef<Partial<Record<ExportFormat, string>>>({});
  const awaitedRequests = useRef<Partial<Record<ExportFormat, { model: string; voice: string; ranges: BlockRange[] }>>>({});
  // A build can end before its POST is answered, so each message is kept until then
  const ended = useRef<Record<string, WSAudioExportMessage>>({});

  const settle = useCallback((format: ExportFormat, error: string | null) => {
    delete awaitedKeys.current[format];
    delete awaitedRequests.current[format];
    setProgress(prev => {
      const next = { ...prev };
      if (error) next[format] = { phase: "failed", error };
      else delete next[format];
      return next;
    });
  }, [setProgress]);

  const save = useCallback(async (state: AudioExportState) => {
    if (!documentId) return;
    const downloading = (fraction: number) => setProgress(prev => ({ ...prev, [state.format]: { phase: "downloading", fraction } }));
    downloading(0);
    // Built, so a socket that reconnects during the download has nothing to ask for again
    delete awaitedRequests.current[state.format];
    try {
      const { data } = await api.get<Blob>(`/v1/documents/${documentId}/audio-export/${state.key}.${state.format}`, {
        responseType: "blob",
        onDownloadProgress: ({ loaded, total }) => { if (total) downloading(loaded / total); },
      });
      const url = URL.createObjectURL(data);
      const anchor = window.document.createElement("a");
      anchor.href = url;
      anchor.download = `${documentTitle || "Document"}.${state.format}`;
      anchor.click();
      URL.revokeObjectURL(url);
      settle(state.format, null);
    } catch (err) {
      console.error("Failed to download audio file:", err);
      const gone = err instanceof AxiosError && err.response?.status === 404;
      settle(state.format, gone ? "The server no longer has this file. Save it again." : "Could not download the file. Please try again.");
    }
  }, [api, documentId, documentTitle, settle, setProgress]);

  const building = useCallback((format: ExportFormat, fraction: number | null) => {
    setProgress(prev => {
      const known = prev[format]?.phase === "building" ? prev[format].fraction : 0;
      return { ...prev, [format]: { phase: "building", fraction: fraction ?? known } };
    });
  }, [setProgress]);

  const conclude = useCallback((message: WSAudioExportMessage) => {
    delete ended.current[message.key];
    if (message.status === "ready") void save(message);
    else settle(message.format, message.error ?? "Building the file failed.");
  }, [save, settle]);

  const receive = useCallback((message: WSAudioExportMessage) => {
    const awaited = awaitedKeys.current[message.format] === message.key;
    if (message.status === "building") { if (awaited) building(message.format, message.progress); }
    else if (awaited) conclude(message);
    else ended.current[message.key] = message;
  }, [building, conclude]);

  const download = useCallback(async (format: ExportFormat, model: string, voice: string, ranges: BlockRange[]) => {
    if (!documentId) return;
    building(format, null);
    awaitedRequests.current[format] = { model, voice, ranges };
    try {
      const { data } = await api.post<AudioExportState>(`/v1/documents/${documentId}/audio-export`, { model, voice, ranges, format });
      awaitedKeys.current[format] = data.key;
      if (data.status === "ready") await save(data);
      else if (ended.current[data.key]) conclude(ended.current[data.key]);
      else building(format, data.progress);
    } catch (err) {
      const detail = err instanceof AxiosError && typeof err.response?.data?.detail === "string" ? err.response.data.detail : null;
      if (!detail) console.error("Failed to export audio:", err);
      settle(format, detail ?? "Could not build the file. Please try again.");
    }
  }, [api, documentId, save, settle, building, conclude]);

  const resume = useCallback(() => {
    for (const [format, request] of Object.entries(awaitedRequests.current)) {
      void download(format as ExportFormat, request.model, request.voice, request.ranges);
    }
  }, [download]);

  return { progress, receive, download, resume };
}

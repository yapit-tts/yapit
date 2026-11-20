import { useCallback, useEffect, useState } from "react";
import { AxiosError } from "axios";
import { useApi } from "@/api";
import type { AudioJob, BlockRange } from "@/lib/audioJob";

// The gateway has no push channel for a job's progress, so a running job is polled.
const POLL_INTERVAL_MS = 4000;

export interface UseAudioJobReturn {
  /** The document's job, running or ended within the last day; null if none. */
  job: AudioJob | null;
  /** Starts a job; resolves to the refusal's reason, or null once it runs. */
  start: (model: string, voice: string, ranges: BlockRange[]) => Promise<string | null>;
  cancel: () => Promise<void>;
}

export function useAudioJob(documentId: string | undefined): UseAudioJobReturn {
  const { api } = useApi();
  const [fetched, setFetched] = useState<{ documentId: string; job: AudioJob | null } | null>(null);
  const job = fetched && fetched.documentId === documentId ? fetched.job : null;

  const refresh = useCallback(async () => {
    if (!documentId) return;
    try {
      const { data } = await api.get<AudioJob>(`/v1/documents/${documentId}/audio-job`);
      setFetched({ documentId, job: data });
    } catch (err) {
      if (err instanceof AxiosError && err.response?.status === 404) setFetched({ documentId, job: null });
      else console.error("Failed to fetch audio job:", err);
    }
  }, [api, documentId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const isRunning = job?.status === "running";
  useEffect(() => {
    if (!isRunning) return;
    const timer = setInterval(() => void refresh(), POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [isRunning, refresh]);

  const start = useCallback(async (model: string, voice: string, ranges: BlockRange[]) => {
    if (!documentId) return "No document";
    try {
      const { data } = await api.post<AudioJob>(`/v1/documents/${documentId}/audio-job`, { model, voice, ranges });
      setFetched({ documentId, job: data });
      return null;
    } catch (err) {
      if (err instanceof AxiosError && typeof err.response?.data?.detail === "string") return err.response.data.detail;
      console.error("Failed to start audio job:", err);
      return "Could not start preparing audio. Please try again.";
    }
  }, [api, documentId]);

  const cancel = useCallback(async () => {
    if (!documentId) return;
    try {
      await api.delete(`/v1/documents/${documentId}/audio-job`);
    } catch (err) {
      console.error("Failed to cancel audio job:", err);
    }
    await refresh();
  }, [api, documentId, refresh]);

  return { job, start, cancel };
}

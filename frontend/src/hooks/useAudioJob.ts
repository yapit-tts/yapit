import { useCallback, useState } from "react";
import { AxiosError } from "axios";
import { useApi } from "@/api";
import type { AudioJob, BlockRange, WSAudioJobMessage } from "@/lib/audioJob";

export interface UseAudioJobReturn {
  /** The document's job, running or ended within the last day; null if none or not heard of yet. */
  job: AudioJob | null;
  /** Takes the job's state as the gateway sends it over the WebSocket. */
  receive: (message: WSAudioJobMessage) => void;
  /** Starts a job; resolves to the refusal's reason, or null once it runs. */
  start: (model: string, voice: string, ranges: BlockRange[]) => Promise<string | null>;
  cancel: () => Promise<void>;
}

/** The document's audio job, as the gateway reports it over the WebSocket the reader holds. */
export function useAudioJob(documentId: string | undefined): UseAudioJobReturn {
  const { api } = useApi();
  const [heard, setHeard] = useState<{ documentId: string; job: AudioJob | null } | null>(null);
  const job = heard && heard.documentId === documentId ? heard.job : null;

  const receive = useCallback((message: WSAudioJobMessage) => {
    setHeard({ documentId: message.document_id, job: message.job });
  }, []);

  const start = useCallback(async (model: string, voice: string, ranges: BlockRange[]) => {
    if (!documentId) return "No document";
    try {
      const { data } = await api.post<AudioJob>(`/v1/documents/${documentId}/audio-job`, { model, voice, ranges });
      setHeard({ documentId, job: data });
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
  }, [api, documentId]);

  return { job, receive, start, cancel };
}

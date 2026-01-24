import { useState, useEffect } from "react";
import { type InworldVoice, type InworldLanguageCode, INWORLD_SLUG } from "@/lib/voiceSelection";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

interface APIVoice {
  id: number;
  slug: string;
  name: string;
  lang: string | null;
  description: string | null;
}

interface UseInworldVoicesReturn {
  voices: InworldVoice[];
  isLoading: boolean;
  error: string | null;
}

// Voices endpoint doesn't require auth, so we can fetch directly
async function fetchVoices(modelSlug: string): Promise<InworldVoice[]> {
  const response = await fetch(`${API_BASE_URL}/v1/models/${modelSlug}/voices`);
  if (!response.ok) {
    throw new Error(`Failed to fetch voices: ${response.status}`);
  }
  const data: APIVoice[] = await response.json();

  return data.map(v => ({
    slug: v.slug,
    name: v.name,
    lang: (v.lang ?? "en") as InworldLanguageCode,
    description: v.description,
  }));
}

// Both inworld and inworld-max share the same voices, so we only need to fetch once
let cachedVoices: InworldVoice[] | null = null;
let fetchPromise: Promise<InworldVoice[]> | null = null;

export function useInworldVoices(): UseInworldVoicesReturn {
  const [voices, setVoices] = useState<InworldVoice[]>(cachedVoices ?? []);
  const [isLoading, setIsLoading] = useState(cachedVoices === null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (cachedVoices) {
      setVoices(cachedVoices);
      setIsLoading(false);
      return;
    }

    // Avoid duplicate fetches
    if (!fetchPromise) {
      fetchPromise = fetchVoices(INWORLD_SLUG);
    }

    fetchPromise
      .then(data => {
        cachedVoices = data;
        setVoices(data);
        setIsLoading(false);
      })
      .catch(err => {
        console.error("[useInworldVoices] Failed to fetch:", err);
        setError(err.message);
        setIsLoading(false);
        fetchPromise = null; // Allow retry
      });
  }, []);

  return { voices, isLoading, error };
}

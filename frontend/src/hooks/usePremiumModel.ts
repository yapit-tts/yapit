import { useState, useEffect } from "react";
import { type ServerVoice } from "@/lib/voiceSelection";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

interface APIVoice {
  id: number;
  slug: string;
  name: string;
  lang: string | null;
  description: string | null;
}

interface APIModel {
  id: number;
  slug: string;
  name: string;
  description: string | null;
  voices: APIVoice[];
}

export interface PremiumModel {
  slug: string;
  name: string;
  voices: ServerVoice[];
}

interface UsePremiumModelReturn {
  model: PremiumModel | null;
  isLoading: boolean;
  error: string | null;
}

let cached: PremiumModel | null | undefined = undefined;
let fetchPromise: Promise<PremiumModel | null> | null = null;

async function fetchPremiumModel(): Promise<PremiumModel | null> {
  const response = await fetch(`${API_BASE_URL}/v1/models`);
  if (!response.ok) throw new Error(`Failed to fetch models: ${response.status}`);

  const models: APIModel[] = await response.json();
  const nonKokoro = models.filter(m => m.slug !== "kokoro");

  const picked = nonKokoro[0] ?? null;
  if (!picked) return null;

  return {
    slug: picked.slug,
    name: picked.name,
    voices: picked.voices.map(v => ({
      slug: v.slug,
      name: v.name,
      lang: (v.lang ?? "en") as ServerVoice["lang"],
      description: v.description,
    })),
  };
}

export function usePremiumModel(): UsePremiumModelReturn {
  const [model, setModel] = useState<PremiumModel | null>(cached ?? null);
  const [isLoading, setIsLoading] = useState(cached === undefined);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (cached !== undefined) {
      setModel(cached);
      setIsLoading(false);
      return;
    }

    if (!fetchPromise) {
      fetchPromise = fetchPremiumModel();
    }

    fetchPromise
      .then(data => {
        cached = data;
        setModel(data);
        setIsLoading(false);
      })
      .catch(err => {
        console.error("[usePremiumModel] Failed to fetch:", err);
        setError(err.message);
        setIsLoading(false);
        fetchPromise = null;
      });
  }, []);

  return { model, isLoading, error };
}

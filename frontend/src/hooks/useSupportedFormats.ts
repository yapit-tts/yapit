import { useEffect, useState } from "react";
import { useApi } from "@/api";

export interface FormatInfo {
  free: boolean;
  ai: boolean;
  has_pages: boolean;
  batch: boolean;
}

export interface SupportedFormats {
  formats: Record<string, FormatInfo>;
  accept: string;
}

// Module-level cache — formats don't change during a session
let cached: SupportedFormats | null = null;

export function useSupportedFormats(): SupportedFormats | null {
  const { api } = useApi();
  const [data, setData] = useState<SupportedFormats | null>(cached);

  useEffect(() => {
    if (cached) return;
    api.get<SupportedFormats>("/v1/documents/supported-formats").then((res) => {
      cached = res.data;
      setData(res.data);
    });
  }, [api]);

  return data;
}

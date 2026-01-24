import { useState, useEffect } from "react";

/**
 * Detects WebGPU support. Returns undefined during SSR/hydration, then resolves to boolean.
 * Used for showing WebGPU warning banner to users who can't run local TTS.
 */
export function useHasWebGPU(): boolean | undefined {
  const [hasWebGPU, setHasWebGPU] = useState<boolean | undefined>(undefined);

  useEffect(() => {
    setHasWebGPU(!!navigator.gpu);
  }, []);

  return hasWebGPU;
}

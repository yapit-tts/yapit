import { useState, useEffect } from "react";

/**
 * Detects actual WebGPU capability via requestAdapter(). Returns undefined
 * during the async check, then resolves to boolean. Treats fallback adapters
 * as unsupported (software impl — WASM q8 is better).
 */
export function useHasWebGPU(): boolean | undefined {
  const [hasWebGPU, setHasWebGPU] = useState<boolean | undefined>(undefined);

  useEffect(() => {
    if (!navigator.gpu) {
      setHasWebGPU(false);
      return;
    }
    navigator.gpu.requestAdapter()
      .then((adapter) => setHasWebGPU(adapter !== null && !adapter.isFallbackAdapter))
      .catch(() => setHasWebGPU(false));
  }, []);

  return hasWebGPU;
}

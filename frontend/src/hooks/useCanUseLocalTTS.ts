import { useHasWebGPU } from "@/hooks/useWebGPU";
import { useIsMobile } from "@/hooks/use-mobile";

/**
 * Whether local (in-browser) TTS is viable on this device.
 * Returns false on mobile (WASM fallback too slow, WebGPU unreliable)
 * and when WebGPU is absent/software-only.
 *
 * undefined while the async WebGPU probe is still running.
 */
export function useCanUseLocalTTS(): boolean | undefined {
  const hasWebGPU = useHasWebGPU();
  const isMobile = useIsMobile();

  if (hasWebGPU === undefined) return undefined;
  return !isMobile && hasWebGPU;
}

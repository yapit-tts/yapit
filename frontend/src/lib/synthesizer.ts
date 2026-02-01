import type { AudioBufferData } from "./playbackEngine";

export interface Synthesizer {
  synthesize(
    blockIdx: number,
    text: string,
    documentId: string,
    model: string,
    voice: string,
  ): Promise<AudioBufferData | null>;

  cancelAll(): void;

  /** Server synthesizer: hint for priority ordering */
  onCursorMove?(documentId: string, cursor: number): void;

  getError(): string | null;
  destroy(): void;
}

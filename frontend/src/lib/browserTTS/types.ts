export type TTSDevice = "webgpu" | "wasm";
export type TTSDtype = "fp32" | "q8";

export interface VoiceInfo {
  name: string;
  language: string;
  gender?: string;
}

// Messages FROM worker TO main thread
export type WorkerMessage =
  | { type: "device"; device: TTSDevice; dtype: TTSDtype }
  | { type: "progress"; progress: number }
  | { type: "ready"; voices: string[] }
  | { type: "audio"; requestId: string; audioData: ArrayBuffer; sampleRate: number }
  | { type: "error"; requestId: string; error: string };

// Messages FROM main thread TO worker
export type MainMessage =
  | { type: "synthesize"; text: string; voice: string; requestId: string };

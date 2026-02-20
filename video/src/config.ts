export const FPS = 30;
export const WIDTH = 1920;
export const HEIGHT = 1080;

export const BRAND = {
  cream: "#faf6f0",
  brown: "#5c4a3a",
  greenDark: "#4a6840",
  green: "#3a8a4d",
  greenLight: "#5aa86a",
  greenPale: "#e8f0e4",
} as const;

export type ThemeName = "light" | "charcoal" | "dusk" | "lavender";

export const THEME_CLASS: Record<ThemeName, string> = {
  light: "theme-light",
  charcoal: "theme-charcoal",
  dusk: "theme-dusk",
  lavender: "theme-lavender",
};

// Scene durations in frames — evolve as we iterate.
// Total must equal 900 (30s) minus transition overlap.
export const SCENES = {
  hook: 90, // 3s — "What if your papers could read themselves?"
  urlPaste: 150, // 5s — paste link → load → document appears
  playback: 210, // 7s — click play, highlighting moves, narrator speaks
  darkModeCycle: 90, // 3s — toggle charcoal → dusk → lavender
  voicePicker: 180, // 6s — scroll through voices, each says a few words
  end: 120, // 4s — yapit branding + CTA
} as const;

export const TRANSITION_FRAMES = 15; // 0.5s overlap per transition

// Clip metadata types — match what capture_trailer.py writes to meta.json
export interface AudioBlockMeta {
  idx: number;
  hash: string;
  path: string;
  size: number;
  duration_s: number;
}

export interface ClipMeta {
  video: string;
  audio: AudioBlockMeta[];
  total_audio_duration_s: number;
  trim_before_s?: number;
}

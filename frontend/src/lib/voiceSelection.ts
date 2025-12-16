// Voice selection types and localStorage utilities

export type ModelType = "kokoro" | "higgs";

export interface VoiceSelection {
  model: ModelType;
  voiceSlug: string;
  // HIGGS-specific settings
  temperature?: number;
  scene?: string;
}

export interface KokoroVoice {
  index: string;
  name: string;
  language: "en-us" | "en-gb";
  gender: "Female" | "Male";
  overallGrade: string;
}

export interface HiggsPreset {
  slug: string;
  name: string;
  description?: string;
}

const VOICE_SELECTION_KEY = "yapit_voice_selection";
const PINNED_VOICES_KEY = "yapit_pinned_voices";

const DEFAULT_SELECTION: VoiceSelection = {
  model: "kokoro",
  voiceSlug: "af_heart",
};

export function getVoiceSelection(): VoiceSelection {
  try {
    const stored = localStorage.getItem(VOICE_SELECTION_KEY);
    if (stored) {
      return JSON.parse(stored);
    }
  } catch {
    // Ignore parse errors
  }
  return DEFAULT_SELECTION;
}

export function setVoiceSelection(selection: VoiceSelection): void {
  localStorage.setItem(VOICE_SELECTION_KEY, JSON.stringify(selection));
}

export function getPinnedVoices(): string[] {
  try {
    const stored = localStorage.getItem(PINNED_VOICES_KEY);
    if (stored) {
      return JSON.parse(stored);
    }
  } catch {
    // Ignore parse errors
  }
  return ["af_heart"]; // Default pin
}

export function setPinnedVoices(slugs: string[]): void {
  localStorage.setItem(PINNED_VOICES_KEY, JSON.stringify(slugs));
}

export function togglePinnedVoice(slug: string): string[] {
  const current = getPinnedVoices();
  const index = current.indexOf(slug);
  if (index >= 0) {
    current.splice(index, 1);
  } else {
    current.push(slug);
  }
  setPinnedVoices(current);
  return current;
}

// Static voice data (could fetch from API later)
export const KOKORO_VOICES: KokoroVoice[] = [
  { index: "af_heart", name: "Heart", language: "en-us", gender: "Female", overallGrade: "A" },
  { index: "af_bella", name: "Bella", language: "en-us", gender: "Female", overallGrade: "A-" },
  { index: "af_nicole", name: "Nicole", language: "en-us", gender: "Female", overallGrade: "B-" },
  { index: "af_aoede", name: "Aoede", language: "en-us", gender: "Female", overallGrade: "C+" },
  { index: "af_kore", name: "Kore", language: "en-us", gender: "Female", overallGrade: "C+" },
  { index: "af_sarah", name: "Sarah", language: "en-us", gender: "Female", overallGrade: "C+" },
  { index: "af_alloy", name: "Alloy", language: "en-us", gender: "Female", overallGrade: "C" },
  { index: "af_nova", name: "Nova", language: "en-us", gender: "Female", overallGrade: "C" },
  { index: "af_sky", name: "Sky", language: "en-us", gender: "Female", overallGrade: "C-" },
  { index: "af_jessica", name: "Jessica", language: "en-us", gender: "Female", overallGrade: "D" },
  { index: "af_river", name: "River", language: "en-us", gender: "Female", overallGrade: "D" },
  { index: "am_fenrir", name: "Fenrir", language: "en-us", gender: "Male", overallGrade: "C+" },
  { index: "am_michael", name: "Michael", language: "en-us", gender: "Male", overallGrade: "C+" },
  { index: "am_puck", name: "Puck", language: "en-us", gender: "Male", overallGrade: "C+" },
  { index: "am_echo", name: "Echo", language: "en-us", gender: "Male", overallGrade: "D" },
  { index: "am_eric", name: "Eric", language: "en-us", gender: "Male", overallGrade: "D" },
  { index: "am_liam", name: "Liam", language: "en-us", gender: "Male", overallGrade: "D" },
  { index: "am_onyx", name: "Onyx", language: "en-us", gender: "Male", overallGrade: "D" },
  { index: "am_santa", name: "Santa", language: "en-us", gender: "Male", overallGrade: "D-" },
  { index: "am_adam", name: "Adam", language: "en-us", gender: "Male", overallGrade: "F+" },
  { index: "bf_emma", name: "Emma", language: "en-gb", gender: "Female", overallGrade: "B-" },
  { index: "bf_isabella", name: "Isabella", language: "en-gb", gender: "Female", overallGrade: "C" },
  { index: "bf_alice", name: "Alice", language: "en-gb", gender: "Female", overallGrade: "D" },
  { index: "bf_lily", name: "Lily", language: "en-gb", gender: "Female", overallGrade: "D" },
  { index: "bm_george", name: "George", language: "en-gb", gender: "Male", overallGrade: "C" },
  { index: "bm_fable", name: "Fable", language: "en-gb", gender: "Male", overallGrade: "C" },
  { index: "bm_lewis", name: "Lewis", language: "en-gb", gender: "Male", overallGrade: "D+" },
  { index: "bm_daniel", name: "Daniel", language: "en-gb", gender: "Male", overallGrade: "D" },
];

export const HIGGS_PRESETS: HiggsPreset[] = [
  { slug: "smart", name: "Smart Voice", description: "Auto-selects based on text" },
  { slug: "belinda", name: "Belinda", description: "Female, US" },
  { slug: "en_man", name: "English Man", description: "Male, US" },
  { slug: "en_woman", name: "English Woman", description: "Female, US" },
  { slug: "chadwick", name: "Chadwick", description: "Male, US" },
];

export const HIGGS_SCENES = [
  { value: "Audio is recorded from a quiet room.", label: "Quiet room" },
  { value: "Audio is a podcast recording with professional quality.", label: "Podcast studio" },
  { value: "Audio is recorded in a noisy cafe.", label: "Noisy cafe" },
  { value: "Audio is recorded from a vintage radio broadcast.", label: "Vintage radio" },
];

// Group Kokoro voices by language and gender
export function groupKokoroVoices(voices: KokoroVoice[]) {
  const groups: Record<string, KokoroVoice[]> = {
    "us-female": [],
    "us-male": [],
    "gb-female": [],
    "gb-male": [],
  };

  for (const voice of voices) {
    const key = `${voice.language === "en-us" ? "us" : "gb"}-${voice.gender.toLowerCase()}`;
    groups[key].push(voice);
  }

  return [
    { key: "us-female", label: "US Female", voices: groups["us-female"] },
    { key: "us-male", label: "US Male", voices: groups["us-male"] },
    { key: "gb-female", label: "UK Female", voices: groups["gb-female"] },
    { key: "gb-male", label: "UK Male", voices: groups["gb-male"] },
  ];
}

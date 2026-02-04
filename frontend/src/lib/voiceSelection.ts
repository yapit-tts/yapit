// Voice selection types and localStorage utilities

export const KOKORO_BROWSER_SLUG = "kokoro-browser" as const;
export const KOKORO_SLUG = "kokoro" as const;
export const INWORLD_SLUG = "inworld-1.5" as const;
export const INWORLD_MAX_SLUG = "inworld-1.5-max" as const;

export type ModelType = typeof KOKORO_BROWSER_SLUG | typeof KOKORO_SLUG | typeof INWORLD_SLUG | typeof INWORLD_MAX_SLUG;

// Check if model is an Inworld model (any variant)
export function isInworldModel(model: ModelType): boolean {
  return model.startsWith("inworld");
}


export function isServerSideModel(model: ModelType): boolean {
  return model !== KOKORO_BROWSER_SLUG;
}

export function isKokoroModel(model: ModelType): boolean {
  return model === KOKORO_BROWSER_SLUG || model === KOKORO_SLUG;
}

export interface VoiceSelection {
  model: ModelType;
  voiceSlug: string;
}

// Kokoro language codes (from voice naming: af=American Female, jm=Japanese Male, etc.)
export type KokoroLanguageCode = "a" | "b" | "j" | "z" | "e" | "f" | "h" | "i" | "p";

export const LANGUAGE_INFO: Record<KokoroLanguageCode, { label: string; flag: string }> = {
  a: { label: "American English", flag: "🇺🇸" },
  b: { label: "British English", flag: "🇬🇧" },
  j: { label: "Japanese", flag: "🇯🇵" },
  z: { label: "Chinese (Mandarin)", flag: "🇨🇳" },
  e: { label: "Spanish", flag: "🇪🇸" },
  f: { label: "French", flag: "🇫🇷" },
  h: { label: "Hindi", flag: "🇮🇳" },
  i: { label: "Italian", flag: "🇮🇹" },
  p: { label: "Portuguese (Brazilian)", flag: "🇧🇷" },
};

export interface KokoroVoice {
  index: string;
  name: string;
  language: KokoroLanguageCode;
  gender: "Female" | "Male";
  grade?: string; // A, B-, C+, etc. - optional since some voices don't have grades
}

const VOICE_SELECTION_KEY = "yapit_voice_selection";
const KOKORO_SELECTION_KEY = "yapit_kokoro_selection";
const INWORLD_SELECTION_KEY = "yapit_inworld_selection";
const PINNED_VOICES_KEY = "yapit_pinned_voices";
const PLAYBACK_SPEED_KEY = "yapit_playback_speed";
const VOLUME_KEY = "yapit_volume";

const DEFAULT_SELECTION: VoiceSelection = {
  model: KOKORO_SLUG,
  voiceSlug: "af_heart",
};

export function getVoiceSelection(): VoiceSelection {
  try {
    const stored = localStorage.getItem(VOICE_SELECTION_KEY);
    if (stored) {
      const parsed = JSON.parse(stored) as VoiceSelection;
      if (parsed.model === ("kokoro-server" as string)) parsed.model = KOKORO_SLUG;
      return parsed;
    }
  } catch { /* localStorage unavailable */ }
  return DEFAULT_SELECTION;
}

export function setVoiceSelection(selection: VoiceSelection): void {
  localStorage.setItem(VOICE_SELECTION_KEY, JSON.stringify(selection));
  // Also save to per-tab storage for tab switching
  if (isKokoroModel(selection.model)) {
    localStorage.setItem(KOKORO_SELECTION_KEY, JSON.stringify(selection));
  } else {
    localStorage.setItem(INWORLD_SELECTION_KEY, JSON.stringify(selection));
  }
}

export function getKokoroSelection(): VoiceSelection | null {
  try {
    const stored = localStorage.getItem(KOKORO_SELECTION_KEY);
    if (stored) {
      const parsed = JSON.parse(stored) as VoiceSelection;
      if (parsed.model === ("kokoro-server" as string)) parsed.model = KOKORO_SLUG;
      return parsed;
    }
  } catch { /* localStorage unavailable */ }
  return null;
}

export function getInworldSelection(): VoiceSelection | null {
  try {
    const stored = localStorage.getItem(INWORLD_SELECTION_KEY);
    if (stored) return JSON.parse(stored) as VoiceSelection;
  } catch { /* localStorage unavailable */ }
  return null;
}

export function getPlaybackSpeed(): number {
  try {
    const stored = localStorage.getItem(PLAYBACK_SPEED_KEY);
    if (stored) return Math.max(0.5, Math.min(3.0, parseFloat(stored)));
  } catch { /* localStorage unavailable */ }
  return 1.0;
}

export function setPlaybackSpeed(speed: number): void {
  localStorage.setItem(PLAYBACK_SPEED_KEY, String(speed));
}

export function getVolume(): number {
  try {
    const stored = localStorage.getItem(VOLUME_KEY);
    if (stored) return Math.max(0, Math.min(100, parseInt(stored)));
  } catch { /* localStorage unavailable */ }
  return 50;
}

export function setVolume(volume: number): void {
  localStorage.setItem(VOLUME_KEY, String(volume));
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

// Grade ordering for sorting (higher = better)
const GRADE_ORDER: Record<string, number> = {
  "A": 100, "A-": 95,
  "B+": 89, "B": 85, "B-": 80,
  "C+": 79, "C": 75, "C-": 70,
  "D+": 69, "D": 65, "D-": 60,
  "F+": 55, "F": 50,
};

function gradeScore(grade?: string): number {
  return grade ? (GRADE_ORDER[grade] ?? 50) : 50;
}

// All 58 Kokoro voices from https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md
export const KOKORO_VOICES: KokoroVoice[] = [
  // American English (20 voices)
  { index: "af_heart", name: "Heart", language: "a", gender: "Female", grade: "A" },
  { index: "af_bella", name: "Bella", language: "a", gender: "Female", grade: "A-" },
  { index: "af_nicole", name: "Nicole", language: "a", gender: "Female", grade: "B-" },
  { index: "af_aoede", name: "Aoede", language: "a", gender: "Female", grade: "C+" },
  { index: "af_kore", name: "Kore", language: "a", gender: "Female", grade: "C+" },
  { index: "af_sarah", name: "Sarah", language: "a", gender: "Female", grade: "C+" },
  { index: "af_alloy", name: "Alloy", language: "a", gender: "Female", grade: "C" },
  { index: "af_nova", name: "Nova", language: "a", gender: "Female", grade: "C" },
  { index: "af_sky", name: "Sky", language: "a", gender: "Female", grade: "C-" },
  { index: "af_jessica", name: "Jessica", language: "a", gender: "Female", grade: "D" },
  { index: "af_river", name: "River", language: "a", gender: "Female", grade: "D" },
  { index: "am_fenrir", name: "Fenrir", language: "a", gender: "Male", grade: "C+" },
  { index: "am_michael", name: "Michael", language: "a", gender: "Male", grade: "C+" },
  { index: "am_puck", name: "Puck", language: "a", gender: "Male", grade: "C+" },
  { index: "am_echo", name: "Echo", language: "a", gender: "Male", grade: "D" },
  { index: "am_eric", name: "Eric", language: "a", gender: "Male", grade: "D" },
  { index: "am_liam", name: "Liam", language: "a", gender: "Male", grade: "D" },
  { index: "am_onyx", name: "Onyx", language: "a", gender: "Male", grade: "D" },
  { index: "am_santa", name: "Santa", language: "a", gender: "Male", grade: "D-" },
  { index: "am_adam", name: "Adam", language: "a", gender: "Male", grade: "F+" },
  // British English (8 voices)
  { index: "bf_emma", name: "Emma", language: "b", gender: "Female", grade: "B-" },
  { index: "bf_isabella", name: "Isabella", language: "b", gender: "Female", grade: "C" },
  { index: "bf_alice", name: "Alice", language: "b", gender: "Female", grade: "D" },
  { index: "bf_lily", name: "Lily", language: "b", gender: "Female", grade: "D" },
  { index: "bm_george", name: "George", language: "b", gender: "Male", grade: "C" },
  { index: "bm_fable", name: "Fable", language: "b", gender: "Male", grade: "C" },
  { index: "bm_lewis", name: "Lewis", language: "b", gender: "Male", grade: "D+" },
  { index: "bm_daniel", name: "Daniel", language: "b", gender: "Male", grade: "D" },
  // Japanese (5 voices)
  { index: "jf_alpha", name: "Alpha", language: "j", gender: "Female", grade: "C+" },
  { index: "jf_gongitsune", name: "Gongitsune", language: "j", gender: "Female", grade: "C" },
  { index: "jf_nezumi", name: "Nezumi", language: "j", gender: "Female", grade: "C-" },
  { index: "jf_tebukuro", name: "Tebukuro", language: "j", gender: "Female", grade: "C" },
  { index: "jm_kumo", name: "Kumo", language: "j", gender: "Male", grade: "C-" },
  // Chinese/Mandarin (8 voices)
  { index: "zf_xiaobei", name: "Xiaobei", language: "z", gender: "Female", grade: "D" },
  { index: "zf_xiaoni", name: "Xiaoni", language: "z", gender: "Female", grade: "D" },
  { index: "zf_xiaoxiao", name: "Xiaoxiao", language: "z", gender: "Female", grade: "D" },
  { index: "zf_xiaoyi", name: "Xiaoyi", language: "z", gender: "Female", grade: "D" },
  { index: "zm_yunjian", name: "Yunjian", language: "z", gender: "Male", grade: "D" },
  { index: "zm_yunxi", name: "Yunxi", language: "z", gender: "Male", grade: "D" },
  { index: "zm_yunxia", name: "Yunxia", language: "z", gender: "Male", grade: "D" },
  { index: "zm_yunyang", name: "Yunyang", language: "z", gender: "Male", grade: "D" },
  // Spanish (3 voices)
  { index: "ef_dora", name: "Dora", language: "e", gender: "Female" },
  { index: "em_alex", name: "Alex", language: "e", gender: "Male" },
  { index: "em_santa", name: "Santa", language: "e", gender: "Male" },
  // French (1 voice)
  { index: "ff_siwis", name: "Siwis", language: "f", gender: "Female", grade: "B-" },
  // Hindi (4 voices)
  { index: "hf_alpha", name: "Alpha", language: "h", gender: "Female", grade: "C" },
  { index: "hf_beta", name: "Beta", language: "h", gender: "Female", grade: "C" },
  { index: "hm_omega", name: "Omega", language: "h", gender: "Male", grade: "C" },
  { index: "hm_psi", name: "Psi", language: "h", gender: "Male", grade: "C" },
  // Italian (2 voices)
  { index: "if_sara", name: "Sara", language: "i", gender: "Female", grade: "C" },
  { index: "im_nicola", name: "Nicola", language: "i", gender: "Male", grade: "C" },
  // Brazilian Portuguese (3 voices)
  { index: "pf_dora", name: "Dora", language: "p", gender: "Female" },
  { index: "pm_alex", name: "Alex", language: "p", gender: "Male" },
  { index: "pm_santa", name: "Santa", language: "p", gender: "Male" },
];

export interface VoiceLanguageGroup {
  language: KokoroLanguageCode;
  label: string;
  flag: string;
  voices: KokoroVoice[];
}

// Language display order by number of speakers (English first, then by global speaker count)
const LANGUAGE_ORDER: KokoroLanguageCode[] = ["a", "b", "z", "h", "e", "f", "p", "j", "i"];

// Group Kokoro voices by language, sorted by quality within each group
export function groupKokoroVoicesByLanguage(voices: KokoroVoice[]): VoiceLanguageGroup[] {
  const byLanguage = new Map<KokoroLanguageCode, KokoroVoice[]>();

  for (const voice of voices) {
    const list = byLanguage.get(voice.language) ?? [];
    list.push(voice);
    byLanguage.set(voice.language, list);
  }

  return LANGUAGE_ORDER
    .filter(lang => byLanguage.has(lang))
    .map(lang => {
      const info = LANGUAGE_INFO[lang];
      const langVoices = byLanguage.get(lang)!;
      // Sort by grade (best first), then alphabetically
      langVoices.sort((a, b) => {
        const gradeDiff = gradeScore(b.grade) - gradeScore(a.grade);
        if (gradeDiff !== 0) return gradeDiff;
        return a.name.localeCompare(b.name);
      });
      return {
        language: lang,
        label: info.label,
        flag: info.flag,
        voices: langVoices,
      };
    });
}

// Check if voice is high quality (A or B tier) - for star indicator
export function isHighQualityVoice(voice: KokoroVoice): boolean {
  return voice.grade !== undefined && gradeScore(voice.grade) >= 80;
}

// Inworld voice types (fetched from API)
export type InworldLanguageCode = "en" | "zh" | "nl" | "fr" | "de" | "it" | "ja" | "ko" | "pl" | "pt" | "es" | "ru" | "hi" | "ar" | "he";

export const INWORLD_LANGUAGE_INFO: Record<InworldLanguageCode, { label: string; flag: string }> = {
  en: { label: "English", flag: "🇺🇸" },
  zh: { label: "Chinese", flag: "🇨🇳" },
  nl: { label: "Dutch", flag: "🇳🇱" },
  fr: { label: "French", flag: "🇫🇷" },
  de: { label: "German", flag: "🇩🇪" },
  it: { label: "Italian", flag: "🇮🇹" },
  ja: { label: "Japanese", flag: "🇯🇵" },
  ko: { label: "Korean", flag: "🇰🇷" },
  pl: { label: "Polish", flag: "🇵🇱" },
  pt: { label: "Portuguese", flag: "🇧🇷" },
  es: { label: "Spanish", flag: "🇪🇸" },
  ru: { label: "Russian", flag: "🇷🇺" },
  hi: { label: "Hindi", flag: "🇮🇳" },
  ar: { label: "Arabic", flag: "🇸🇦" },
  he: { label: "Hebrew", flag: "🇮🇱" },
};

// Sorted by global speaker count
// Sorted by total speakers (Ethnologue 2025)
// https://en.wikipedia.org/wiki/List_of_languages_by_total_number_of_speakers
const INWORLD_LANGUAGE_ORDER: InworldLanguageCode[] = ["en", "zh", "hi", "es", "ar", "fr", "pt", "ru", "de", "ja", "ko", "it", "pl", "nl", "he"];

export interface InworldVoice {
  slug: string;
  name: string;
  lang: InworldLanguageCode;
  description: string | null;
}

export interface InworldVoiceLanguageGroup {
  language: InworldLanguageCode;
  label: string;
  flag: string;
  voices: InworldVoice[];
}

// Group Inworld voices by language
export function groupInworldVoicesByLanguage(voices: InworldVoice[]): InworldVoiceLanguageGroup[] {
  const byLanguage = new Map<InworldLanguageCode, InworldVoice[]>();

  for (const voice of voices) {
    const list = byLanguage.get(voice.lang) ?? [];
    list.push(voice);
    byLanguage.set(voice.lang, list);
  }

  return INWORLD_LANGUAGE_ORDER
    .filter(lang => byLanguage.has(lang))
    .map(lang => {
      const info = INWORLD_LANGUAGE_INFO[lang];
      const langVoices = byLanguage.get(lang)!;
      // Sort alphabetically by name
      langVoices.sort((a, b) => a.name.localeCompare(b.name));
      return {
        language: lang,
        label: info.label,
        flag: info.flag,
        voices: langVoices,
      };
    });
}

// Legacy function for backwards compatibility (deprecated)
export function groupKokoroVoices(voices: KokoroVoice[]) {
  const groups = groupKokoroVoicesByLanguage(voices);
  // Return in old format for any code still using it
  const americanGroup = groups.find(g => g.language === "a");
  const britishGroup = groups.find(g => g.language === "b");
  return [
    { key: "us-female", label: "US Female", voices: americanGroup?.voices.filter(v => v.gender === "Female") ?? [] },
    { key: "us-male", label: "US Male", voices: americanGroup?.voices.filter(v => v.gender === "Male") ?? [] },
    { key: "gb-female", label: "UK Female", voices: britishGroup?.voices.filter(v => v.gender === "Female") ?? [] },
    { key: "gb-male", label: "UK Male", voices: britishGroup?.voices.filter(v => v.gender === "Male") ?? [] },
  ];
}

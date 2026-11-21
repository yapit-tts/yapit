/** Which redesign of the audio dialog to show, from `?audio=a|b|c`; null keeps the dialog as built. For comparing the variants only. */
export type AudioVariant = "a" | "b" | "c";

export function audioVariant(): AudioVariant | null {
  const value = new URLSearchParams(window.location.search).get("audio");
  return value === "a" || value === "b" || value === "c" ? value : null;
}

/** Opens variant C's panel from outside it, such as from the playback bar. */
export const OPEN_AUDIO_PANEL_EVENT = "open-audio-panel";

/** The reading page's keys and what each does, as the shortcuts dialog and the Tips page list them. */
export const KEYBOARD_SHORTCUTS = [
  ["Space", "Play / pause"],
  ["j ↓", "Next block"],
  ["k ↑", "Previous block"],
  ["l →", "Speed up"],
  ["h ←", "Speed down"],
  ["m", "Mute / unmute"],
  ["+ / =", "Volume up"],
  ["-", "Volume down"],
  ["s", "Toggle sidebar"],
  ["o", "Toggle outliner"],
  ["r", "Back to reading"],
  ["c", "Copy markdown"],
  ["d", "Download markdown"],
  ["g", "Generate in background"],
  ["?", "This dialog"],
  ["⌘K", "Search documents"],
] as const;

/**
 * Whether a key press is the page's to act on: no Ctrl, Cmd or Alt held, so the browser's own combinations pass, and
 * no text field, editable title or dialog holding focus.
 */
export function isPageShortcut(e: KeyboardEvent): boolean {
  if (e.ctrlKey || e.metaKey || e.altKey) return false;
  const el = e.target as HTMLElement;
  if (["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName) || el.isContentEditable) return false;
  return !el.closest('[role="dialog"]');
}

import { useState, useEffect, useCallback } from "react";

export interface AppSettings {
  scrollOnRestore: boolean;
  liveScrollTracking: boolean;
  defaultSpeed: number;
  defaultVoice: string;
}

const SETTINGS_KEY = "yapit-settings";

const defaultSettings: AppSettings = {
  scrollOnRestore: true,
  liveScrollTracking: true,
  defaultSpeed: 1.0,
  defaultVoice: "heart", // Kokoro default
};

function loadSettings(): AppSettings {
  try {
    const stored = localStorage.getItem(SETTINGS_KEY);
    if (stored) {
      return { ...defaultSettings, ...JSON.parse(stored) };
    }
  } catch (e) {
    console.warn("Failed to load settings:", e);
  }
  return defaultSettings;
}

function saveSettings(settings: AppSettings): void {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  } catch (e) {
    console.warn("Failed to save settings:", e);
  }
}

export function useSettings() {
  const [settings, setSettingsState] = useState<AppSettings>(loadSettings);

  // Sync across tabs
  useEffect(() => {
    const handler = (e: StorageEvent) => {
      if (e.key === SETTINGS_KEY && e.newValue) {
        setSettingsState({ ...defaultSettings, ...JSON.parse(e.newValue) });
      }
    };
    window.addEventListener("storage", handler);
    return () => window.removeEventListener("storage", handler);
  }, []);

  const setSettings = useCallback((updates: Partial<AppSettings>) => {
    setSettingsState((prev) => {
      const next = { ...prev, ...updates };
      saveSettings(next);
      return next;
    });
  }, []);

  return { settings, setSettings };
}

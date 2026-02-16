import { useState, useEffect, useCallback, useContext, createContext, ReactNode } from "react";

export type ContentWidth = "narrow" | "medium" | "wide" | "full";
export type ScrollPosition = "top" | "center" | "bottom";
export type Theme = "light" | "dark" | "system";

export interface AppSettings {
  scrollOnRestore: boolean;
  liveScrollTracking: boolean;
  contentWidth: ContentWidth;
  scrollPosition: ScrollPosition;
  theme: Theme;
}

const SETTINGS_KEY = "yapit-settings";

const defaultSettings: AppSettings = {
  scrollOnRestore: true,
  liveScrollTracking: true,
  contentWidth: "medium",
  scrollPosition: "top",
  theme: "system",
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

function resolveTheme(theme: Theme, systemDark: boolean): boolean {
  if (theme === "system") return systemDark;
  return theme === "dark";
}

interface SettingsContextValue {
  settings: AppSettings;
  setSettings: (updates: Partial<AppSettings>) => void;
}

const SettingsContext = createContext<SettingsContextValue | null>(null);

export function SettingsProvider({ children }: { children: ReactNode }) {
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

  // Apply theme to document
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      const dark = resolveTheme(settings.theme, mq.matches);
      document.documentElement.classList.toggle("dark", dark);
    };

    apply();

    if (settings.theme === "system") {
      mq.addEventListener("change", apply);
      return () => mq.removeEventListener("change", apply);
    }
  }, [settings.theme]);

  const setSettings = useCallback((updates: Partial<AppSettings>) => {
    setSettingsState((prev) => {
      const next = { ...prev, ...updates };
      saveSettings(next);
      return next;
    });
  }, []);

  return (
    <SettingsContext.Provider value={{ settings, setSettings }}>
      {children}
    </SettingsContext.Provider>
  );
}

export function useSettings() {
  const context = useContext(SettingsContext);
  if (!context) {
    throw new Error("useSettings must be used within a SettingsProvider");
  }
  return context;
}

export function useIsDark(): boolean {
  const { settings } = useSettings();
  const [systemDark, setSystemDark] = useState(
    () => window.matchMedia("(prefers-color-scheme: dark)").matches
  );

  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = (e: MediaQueryListEvent) => setSystemDark(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  return resolveTheme(settings.theme, systemDark);
}

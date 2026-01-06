import { createContext, useContext, useEffect, useState, useCallback, FC, PropsWithChildren, useRef } from "react";
import { useApi } from "@/api";
import { getPinnedVoices, setPinnedVoices as setLocalPinnedVoices } from "@/lib/voiceSelection";

interface UserPreferences {
  pinnedVoices: string[];
  togglePinnedVoice: (slug: string) => string[];
  isLoading: boolean;
}

const UserPreferencesContext = createContext<UserPreferences>({
  pinnedVoices: [],
  togglePinnedVoice: () => [],
  isLoading: true,
});

interface PreferencesResponse {
  pinned_voices: string[];
}

export const UserPreferencesProvider: FC<PropsWithChildren> = ({ children }) => {
  const { api, isAuthReady, isAnonymous } = useApi();
  const [pinnedVoices, setPinnedVoices] = useState<string[]>(() => getPinnedVoices());
  const [isLoading, setIsLoading] = useState(true);
  const hasFetched = useRef(false);

  // Track isAnonymous via ref for use in callbacks
  const isAnonymousRef = useRef(isAnonymous);
  isAnonymousRef.current = isAnonymous;

  // Fetch server preferences on init for authenticated users
  useEffect(() => {
    if (!isAuthReady) return;

    if (isAnonymous) {
      // Anonymous users just use localStorage
      setIsLoading(false);
      return;
    }

    // Only fetch once per session
    if (hasFetched.current) return;
    hasFetched.current = true;

    const fetchPreferences = async () => {
      try {
        const response = await api.get<PreferencesResponse>("/v1/users/me/preferences");
        const serverPinned = response.data.pinned_voices;
        const localPinned = getPinnedVoices();

        // Merge: union of server and local, server takes precedence for ordering
        const merged = [...new Set([...serverPinned, ...localPinned])];
        setPinnedVoices(merged);
        setLocalPinnedVoices(merged);

        // Sync merged list back to server if local had additions
        if (localPinned.some(v => !serverPinned.includes(v))) {
          api.patch("/v1/users/me/preferences", { pinned_voices: merged }).catch(() => {});
        }
      } catch (error) {
        console.error("Failed to fetch user preferences:", error);
        // Fall back to localStorage on error
      } finally {
        setIsLoading(false);
      }
    };

    fetchPreferences();
  }, [api, isAuthReady, isAnonymous]);

  const togglePinnedVoice = useCallback((slug: string): string[] => {
    const newPinned = [...pinnedVoices];
    const index = newPinned.indexOf(slug);
    if (index >= 0) {
      newPinned.splice(index, 1);
    } else {
      newPinned.push(slug);
    }

    setPinnedVoices(newPinned);
    setLocalPinnedVoices(newPinned);

    // Sync to server for authenticated users
    if (!isAnonymousRef.current) {
      api.patch("/v1/users/me/preferences", { pinned_voices: newPinned }).catch(() => {
        // Silently ignore sync failures - localStorage is the fallback
      });
    }

    return newPinned;
  }, [pinnedVoices, api]);

  return (
    <UserPreferencesContext.Provider value={{ pinnedVoices, togglePinnedVoice, isLoading }}>
      {children}
    </UserPreferencesContext.Provider>
  );
};

export function useUserPreferences(): UserPreferences {
  return useContext(UserPreferencesContext);
}

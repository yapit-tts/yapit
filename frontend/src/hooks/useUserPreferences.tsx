import { createContext, useContext, useEffect, useState, useCallback, FC, PropsWithChildren, useRef } from "react";
import { useApi } from "@/api";
import { getPinnedVoices, setPinnedVoices as setLocalPinnedVoices } from "@/lib/voiceSelection";

interface UserPreferences {
  pinnedVoices: string[];
  togglePinnedVoice: (slug: string) => string[];
  autoImportSharedDocuments: boolean;
  setAutoImportSharedDocuments: (value: boolean) => void;
  defaultDocumentsPublic: boolean;
  setDefaultDocumentsPublic: (value: boolean) => void;
  isLoading: boolean;
}

const UserPreferencesContext = createContext<UserPreferences>({
  pinnedVoices: [],
  togglePinnedVoice: () => [],
  autoImportSharedDocuments: false,
  setAutoImportSharedDocuments: () => {},
  defaultDocumentsPublic: false,
  setDefaultDocumentsPublic: () => {},
  isLoading: true,
});

interface PreferencesResponse {
  pinned_voices: string[];
  auto_import_shared_documents: boolean;
  default_documents_public: boolean;
}

export const UserPreferencesProvider: FC<PropsWithChildren> = ({ children }) => {
  const { api, isAuthReady, isAnonymous } = useApi();
  const [pinnedVoices, setPinnedVoices] = useState<string[]>(() => getPinnedVoices());
  const [autoImportSharedDocuments, setAutoImportSharedDocumentsState] = useState(false);
  const [defaultDocumentsPublic, setDefaultDocumentsPublicState] = useState(false);
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

        // Set sharing preferences from server
        setAutoImportSharedDocumentsState(response.data.auto_import_shared_documents);
        setDefaultDocumentsPublicState(response.data.default_documents_public);

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

  const setAutoImportSharedDocuments = useCallback((value: boolean) => {
    setAutoImportSharedDocumentsState(value);
    if (!isAnonymousRef.current) {
      api.patch("/v1/users/me/preferences", { auto_import_shared_documents: value }).catch(() => {});
    }
  }, [api]);

  const setDefaultDocumentsPublic = useCallback((value: boolean) => {
    setDefaultDocumentsPublicState(value);
    if (!isAnonymousRef.current) {
      api.patch("/v1/users/me/preferences", { default_documents_public: value }).catch(() => {});
    }
  }, [api]);

  return (
    <UserPreferencesContext.Provider value={{
      pinnedVoices,
      togglePinnedVoice,
      autoImportSharedDocuments,
      setAutoImportSharedDocuments,
      defaultDocumentsPublic,
      setDefaultDocumentsPublic,
      isLoading,
    }}>
      {children}
    </UserPreferencesContext.Provider>
  );
};

export function useUserPreferences(): UserPreferences {
  return useContext(UserPreferencesContext);
}

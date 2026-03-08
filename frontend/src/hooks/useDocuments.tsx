import { createContext, useContext, useEffect, useState } from "react";
import { useLocation } from "react-router";
import { useApi } from "@/api";
import { useUser } from "@stackframe/react";

export interface DocumentItem {
  id: string;
  title: string | null;
  created: string;
  is_public: boolean;
}

interface DocumentsContextValue {
  documents: DocumentItem[];
  setDocuments: React.Dispatch<React.SetStateAction<DocumentItem[]>>;
  isLoading: boolean;
}

const DocumentsContext = createContext<DocumentsContextValue | null>(null);

export function DocumentsProvider({ children }: { children: React.ReactNode }) {
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const { api, isAuthReady } = useApi();
  const user = useUser();
  const location = useLocation();

  useEffect(() => {
    if (!isAuthReady) return;

    api.get<DocumentItem[]>("/v1/documents")
      .then((r) => setDocuments(r.data))
      .catch((err) => console.error("Failed to fetch documents:", err))
      .finally(() => setIsLoading(false));
  }, [api, isAuthReady, user, location.pathname]);

  useEffect(() => {
    const handleTitleChanged = (e: Event) => {
      const { documentId, title } = (e as CustomEvent).detail;
      setDocuments((prev) => prev.map((d) => d.id === documentId ? { ...d, title } : d));
    };
    window.addEventListener("document-title-changed", handleTitleChanged);
    return () => window.removeEventListener("document-title-changed", handleTitleChanged);
  }, []);

  useEffect(() => {
    const refetch = () => {
      api.get<DocumentItem[]>("/v1/documents")
        .then((r) => setDocuments(r.data))
        .catch(console.error);
    };
    window.addEventListener("documents-changed", refetch);
    return () => window.removeEventListener("documents-changed", refetch);
  }, [api]);

  return (
    <DocumentsContext value={{ documents, setDocuments, isLoading }}>
      {children}
    </DocumentsContext>
  );
}

export function useDocuments() {
  const ctx = useContext(DocumentsContext);
  if (!ctx) throw new Error("useDocuments must be used within DocumentsProvider");
  return ctx;
}

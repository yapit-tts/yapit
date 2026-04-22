import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { useLocation } from "react-router";
import { useApi } from "@/api";
import { useAuthUser } from "@/hooks/useAuthUser";

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
  hasMore: boolean;
  isFetchingMore: boolean;
  loadMore: () => void;
}

const DocumentsContext = createContext<DocumentsContextValue | null>(null);

const PAGE_SIZE = 50;

export function DocumentsProvider({ children }: { children: React.ReactNode }) {
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [hasMore, setHasMore] = useState(false);
  const [isFetchingMore, setIsFetchingMore] = useState(false);
  const { api, isAuthReady } = useApi();
  const user = useAuthUser();
  const location = useLocation();

  const documentsRef = useRef(documents);
  documentsRef.current = documents;
  const isFetchingMoreRef = useRef(false);

  useEffect(() => {
    if (!isAuthReady) return;

    api.get<DocumentItem[]>("/v1/documents", { params: { offset: 0, limit: PAGE_SIZE } })
      .then((r) => {
        setDocuments(r.data);
        setHasMore(r.data.length === PAGE_SIZE);
      })
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
      api.get<DocumentItem[]>("/v1/documents", { params: { offset: 0, limit: PAGE_SIZE } })
        .then((r) => {
          setDocuments(r.data);
          setHasMore(r.data.length === PAGE_SIZE);
        })
        .catch(console.error);
    };
    window.addEventListener("documents-changed", refetch);
    return () => window.removeEventListener("documents-changed", refetch);
  }, [api]);

  const loadMore = useCallback(() => {
    if (isFetchingMoreRef.current) return;
    isFetchingMoreRef.current = true;
    setIsFetchingMore(true);

    const offset = documentsRef.current.length;
    api.get<DocumentItem[]>("/v1/documents", { params: { offset, limit: PAGE_SIZE } })
      .then((r) => {
        setDocuments((prev) => {
          const seen = new Set(prev.map((d) => d.id));
          return [...prev, ...r.data.filter((d) => !seen.has(d.id))];
        });
        setHasMore(r.data.length === PAGE_SIZE);
      })
      .catch((err) => console.error("Failed to fetch more documents:", err))
      .finally(() => {
        isFetchingMoreRef.current = false;
        setIsFetchingMore(false);
      });
  }, [api]);

  return (
    <DocumentsContext value={{ documents, setDocuments, isLoading, hasMore, isFetchingMore, loadMore }}>
      {children}
    </DocumentsContext>
  );
}

export function useDocuments() {
  const ctx = useContext(DocumentsContext);
  if (!ctx) throw new Error("useDocuments must be used within DocumentsProvider");
  return ctx;
}

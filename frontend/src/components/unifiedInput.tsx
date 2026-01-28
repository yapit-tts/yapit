import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate, Link } from "react-router";
import { Paperclip, Loader2, AlertCircle, Play, Info } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { MetadataBanner } from "@/components/metadataBanner";
import { useDebounce } from "@/hooks/useDebounce";
import { useApi } from "@/api";
import { cn } from "@/lib/utils";
import { AxiosError } from "axios";

// Match URLs with at least a domain and TLD (e.g., example.com, not just http://a)
const URL_REGEX = /^https?:\/\/[^\s.]+\.[^\s]{2,}/i;
const AI_TRANSFORM_STORAGE_KEY = "yapit-ai-transform-enabled";

interface DocumentMetadata {
  content_type: string;
  total_pages: number;
  title: string | null;
  url: string | null;
  file_name: string | null;
  file_size: number | null;
}

interface PrepareResponse {
  hash: string;
  content_hash: string;
  metadata: DocumentMetadata;
  endpoint: "text" | "website" | "document";
  credit_cost: string;
  uncached_pages: number[];
}

interface ExtractionStatusResponse {
  total_pages: number;
  completed_pages: number[];
  status: "processing" | "complete" | "not_found";
}

interface DocumentCreateResponse {
  id: string;
  title: string | null;
  failed_pages: number[];  // 0-indexed pages that failed extraction
}

type InputMode = "idle" | "text" | "url" | "file";
type UrlState = "detecting" | "loading" | "ready" | "error";

const ACCEPTED_FILE_TYPES = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/msword",
  "text/plain",
  "text/html",
  "text/markdown",
  "text/x-markdown",
  "application/epub+zip",
];

const MAX_FILE_SIZE_MB = 50;
const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024;

export function UnifiedInput() {
  const [value, setValue] = useState("");
  const [mode, setMode] = useState<InputMode>("idle");
  const [urlState, setUrlState] = useState<UrlState>("detecting");
  const [prepareData, setPrepareData] = useState<PrepareResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [aiTransformEnabled, setAiTransformEnabled] = useState(() => {
    const stored = localStorage.getItem(AI_TRANSFORM_STORAGE_KEY);
    return stored !== null ? stored === "true" : true;
  });
  const [usageLimitExceeded, setUsageLimitExceeded] = useState(false);
  const [storageLimitError, setStorageLimitError] = useState<string | null>(null);
  const [completedPages, setCompletedPages] = useState<number[]>([]);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const dragCounterRef = useRef(0);
  const abortControllerRef = useRef<AbortController | null>(null);
  const navigate = useNavigate();
  const { api } = useApi();

  const debouncedValue = useDebounce(value, 400);

  const isUrl = useCallback((text: string) => URL_REGEX.test(text.trim()), []);

  // Reset state when home button clicked while on home
  useEffect(() => {
    const handleReset = () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
        abortControllerRef.current = null;
      }
      setValue("");
      setMode("idle");
      setUrlState("detecting");
      setPrepareData(null);
      setError(null);
      setIsCreating(false);
      setStorageLimitError(null);
      setUsageLimitExceeded(false);
      setCompletedPages([]);
    };
    window.addEventListener("reset-input", handleReset);
    return () => window.removeEventListener("reset-input", handleReset);
  }, []);

  // Detect input type and update mode
  useEffect(() => {
    // Don't change mode while processing or loading
    if (isCreating) return;

    const trimmed = value.trim();
    if (!trimmed) {
      setMode("idle");
      setUrlState("detecting");
      setPrepareData(null);
      setError(null);
      setStorageLimitError(null);
      return;
    }

    // Don't change mode while URL metadata is loading or ready
    if (urlState === "loading" || urlState === "ready") return;

    // If in file mode, only reset if value is completely cleared (handled above)
    if (mode === "file") return;

    if (isUrl(trimmed)) {
      setMode("url");
      setUrlState("detecting");
    } else if (mode !== "text") {
      // Only reset when transitioning TO text mode, not when already in text mode
      setMode("text");
      setPrepareData(null);
      setError(null);
      setStorageLimitError(null);
    }
  }, [value, isUrl, mode, isCreating, urlState]);

  // Fetch metadata when URL is detected (debounced)
  useEffect(() => {
    if (mode !== "url" || !debouncedValue.trim()) return;
    if (!isUrl(debouncedValue)) return;

    const fetchMetadata = async () => {
      setUrlState("loading");
      setError(null);
      setPrepareData(null);

      try {
        const response = await api.post<PrepareResponse>("/v1/documents/prepare", {
          url: debouncedValue.trim(),
        });
        setPrepareData(response.data);

        // Auto-create for websites
        if (response.data.endpoint === "website") {
          await createDocument(response.data);
        } else {
          setUrlState("ready");
        }
      } catch (err) {
        setUrlState("error");
        if (err instanceof AxiosError && err.response) {
          // Use backend's error message if available (it's now user-friendly)
          const detail = err.response.data?.detail;
          setError(detail || err.message);
        } else {
          setError(err instanceof Error ? err.message : "Failed to fetch URL");
        }
      }
    };

    fetchMetadata();
  }, [debouncedValue, mode, isUrl, api]);

  // Save AI Transform preference
  useEffect(() => {
    localStorage.setItem(AI_TRANSFORM_STORAGE_KEY, String(aiTransformEnabled));
  }, [aiTransformEnabled]);

  const createDocument = async (data: PrepareResponse, pages: number[] | null = null) => {
    setIsCreating(true);
    setCompletedPages([]);

    // Create abort controller for this request
    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    const endpoint = data.endpoint === "website"
      ? "/v1/documents/website"
      : "/v1/documents/document";

    const isImage = data.metadata.content_type?.startsWith("image/") ?? false;
    const useAiTransform = isImage || aiTransformEnabled;
    const body = data.endpoint === "website"
      ? { hash: data.hash }
      : {
          hash: data.hash,
          pages: pages,
          ai_transform: useAiTransform,
        };

    // Start polling for progress (only for documents with AI transform)
    let pollInterval: ReturnType<typeof setInterval> | null = null;
    if (data.endpoint === "document" && useAiTransform) {
      const requestedPages = pages ?? Array.from({ length: data.metadata.total_pages }, (_, i) => i);
      const processorSlug = useAiTransform ? "gemini" : "markitdown";

      pollInterval = setInterval(async () => {
        try {
          const statusResponse = await api.post<ExtractionStatusResponse>("/v1/documents/extraction/status", {
            content_hash: data.content_hash,
            processor_slug: processorSlug,
            pages: requestedPages,
          });
          setCompletedPages(statusResponse.data.completed_pages);
        } catch (err) {
          // Log but don't fail — polling is just for UI feedback, main POST handles real errors
          console.warn("Extraction status poll failed (non-critical):", err);
        }
      }, 1500);
    }

    try {
      const response = await api.post<DocumentCreateResponse>(endpoint, body, {
        signal: abortController.signal,
      });

      if (pollInterval) clearInterval(pollInterval);
      abortControllerRef.current = null;

      // Pass failed pages info to the listen page if any
      const failedPages = response.data.failed_pages ?? [];
      navigate(`/listen/${response.data.id}`, {
        state: {
          documentTitle: response.data.title,
          failedPages: failedPages.length > 0 ? failedPages : undefined,
        }
      });
    } catch (err) {
      if (pollInterval) clearInterval(pollInterval);
      abortControllerRef.current = null;
      setIsCreating(false);
      setCompletedPages([]);

      // Don't show error if user cancelled
      if (err instanceof AxiosError && err.code === "ERR_CANCELED") {
        return;
      }

      const axiosErr = err as AxiosError<{ detail?: { code?: string; message?: string } | string }>;
      const detail = axiosErr.response?.data?.detail;
      if (axiosErr.response?.status === 402) {
        setAiTransformEnabled(false);
        setUsageLimitExceeded(true);
        setError(null);
      } else if (typeof detail === "object" && detail?.code === "STORAGE_LIMIT_EXCEEDED") {
        setStorageLimitError(detail.message || "Storage limit reached");
        setError(null);
      } else {
        setError(err instanceof Error ? err.message : "Failed to create document");
      }
    }
  };

  const cancelExtraction = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
  }, []);

  const handleTextSubmit = async () => {
    if (!value.trim()) return;
    setIsCreating(true);

    try {
      const response = await api.post<DocumentCreateResponse>("/v1/documents/text", {
        content: value.trim(),
      });
      navigate(`/listen/${response.data.id}`, {
        state: { documentTitle: response.data.title }
      });
    } catch (err) {
      setIsCreating(false);
      const axiosErr = err as AxiosError<{ detail?: { code?: string; message?: string } | string }>;
      const detail = axiosErr.response?.data?.detail;
      if (typeof detail === "object" && detail?.code === "STORAGE_LIMIT_EXCEEDED") {
        setStorageLimitError(detail.message || "Storage limit reached");
        setError(null);
      } else {
        setError(err instanceof Error ? err.message : "Failed to create document");
      }
    }
  };

  const uploadFile = useCallback(async (file: File) => {
    setMode("file");
    setError(null);
    setValue(file.name);

    if (file.size > MAX_FILE_SIZE_BYTES) {
      setUrlState("error");
      setError(`File too large (${(file.size / 1024 / 1024).toFixed(1)} MB). Maximum size is ${MAX_FILE_SIZE_MB} MB.`);
      return;
    }

    setUrlState("loading");

    try {
      const formData = new FormData();
      formData.append("file", file);

      const response = await api.post<PrepareResponse>("/v1/documents/prepare/upload", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });

      const contentType = response.data.metadata.content_type;

      // Auto-create for text-based files (no OCR option needed)
      const isTextBased = ["text/plain", "text/markdown", "text/x-markdown", "text/html"].includes(contentType);
      if (isTextBased) {
        setIsCreating(true);
        const docResponse = await api.post<DocumentCreateResponse>("/v1/documents/document", {
          hash: response.data.hash,
          pages: null,
          processor_slug: "markitdown",
        });
        navigate(`/listen/${docResponse.data.id}`, {
          state: { documentTitle: docResponse.data.title }
        });
      } else {
        setPrepareData(response.data);
        setUrlState("ready");
      }
    } catch (err) {
      setUrlState("error");
      setIsCreating(false);
      const axiosErr = err as AxiosError<{ detail?: { code?: string; message?: string } | string }>;
      const detail = axiosErr.response?.data?.detail;
      if (typeof detail === "object" && detail?.code === "STORAGE_LIMIT_EXCEEDED") {
        setStorageLimitError(detail.message || "Storage limit reached");
        setError(null);
      } else if (axiosErr.response?.status === 413) {
        setError(`File too large. Maximum size is ${MAX_FILE_SIZE_MB} MB.`);
      } else if (typeof detail === "string") {
        setError(detail);
      } else if (typeof detail === "object" && detail?.message) {
        setError(detail.message);
      } else {
        setError(err instanceof Error ? err.message : "Failed to upload file");
      }
    }
  }, [api, navigate]);

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    await uploadFile(file);
  };

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current++;
    if (e.dataTransfer.items && e.dataTransfer.items.length > 0) {
      setIsDragging(true);
    }
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current--;
    if (dragCounterRef.current === 0) {
      setIsDragging(false);
    }
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    dragCounterRef.current = 0;

    const files = e.dataTransfer.files;
    if (files.length === 0) return;

    const file = files[0];
    const isAcceptedType = ACCEPTED_FILE_TYPES.includes(file.type) ||
      file.name.match(/\.(pdf|docx?|txt|md|html?|epub)$/i);

    if (!isAcceptedType) {
      setError(`Unsupported file type: ${file.type || file.name.split('.').pop()}`);
      return;
    }

    await uploadFile(file);
  }, [uploadFile]);

  const handleAiTransformToggle = useCallback((enabled: boolean) => {
    setAiTransformEnabled(enabled);
    if (enabled) {
      setUsageLimitExceeded(false);
    }
  }, []);

  const showMetadataBanner = (mode === "url" || mode === "file") && urlState === "ready" && prepareData?.endpoint === "document";
  const showTextMode = mode === "text" || mode === "idle";
  const isLoadingUrl = (mode === "url" || mode === "file") && (urlState === "loading" || urlState === "detecting");

  return (
    <div
      className="flex flex-col w-full max-w-2xl mx-auto gap-4"
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      <div className="relative">
        <Textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Paste a URL, drop a file, or type text..."
          className={cn(
            "min-h-[140px] pr-14 resize-none transition-all text-base",
            mode === "text" && "min-h-[220px]",
            error && "border-destructive",
            isDragging && "border-primary border-2 border-dashed"
          )}
          disabled={isCreating}
        />

        <div className="absolute right-3 top-3 flex flex-col gap-2">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={() => fileInputRef.current?.click()}
            disabled={isCreating || isLoadingUrl}
            className="h-10 w-10"
          >
            <Paperclip className="h-5 w-5" />
          </Button>
        </div>

        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.docx,.doc,.txt,.md,.html,.htm,.epub"
          onChange={handleFileSelect}
          className="hidden"
        />

        {isDragging && (
          <div className="absolute inset-0 bg-primary/10 flex items-center justify-center rounded-md pointer-events-none">
            <span className="text-primary font-medium">Drop file here</span>
          </div>
        )}

        {isLoadingUrl && !isDragging && (
          <div className="absolute inset-0 bg-background/50 flex items-center justify-center rounded-md">
            <Loader2 className="h-6 w-6 animate-spin text-primary" />
          </div>
        )}
      </div>

      {error && (
        <div className="flex items-center gap-2 text-sm text-destructive">
          <AlertCircle className="h-4 w-4" />
          {error}
        </div>
      )}

      {usageLimitExceeded && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Info className="h-4 w-4 shrink-0" />
          <span>
            This request exceeds your current plan's usage limits.{" "}
            <Link to="/subscription" className="text-primary hover:underline">
              Upgrade plan
            </Link>
          </span>
        </div>
      )}

      {storageLimitError && (
        <div className="flex items-center gap-2 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span>
            {storageLimitError}{" "}
            <Link to="/account" className="text-primary hover:underline">
              Manage documents
            </Link>
          </span>
        </div>
      )}

      {showMetadataBanner && prepareData && (
        <MetadataBanner
          metadata={prepareData.metadata}
          aiTransformEnabled={aiTransformEnabled}
          onAiTransformToggle={handleAiTransformToggle}
          onConfirm={(pages) => createDocument(prepareData, pages)}
          onCancel={cancelExtraction}
          isLoading={isCreating}
          completedPages={completedPages}
          uncachedPages={prepareData.uncached_pages}
        />
      )}

      {showTextMode && value.trim() && (
        <Button
          onClick={handleTextSubmit}
          disabled={isCreating}
          variant="secondary"
          size="lg"
          className="self-start"
        >
          {isCreating ? (
            <>
              <Loader2 className="h-5 w-5 animate-spin" />
              Processing...
            </>
          ) : (
            <>
              <Play className="h-5 w-5" />
              Start Listening
            </>
          )}
        </Button>
      )}
    </div>
  );
}

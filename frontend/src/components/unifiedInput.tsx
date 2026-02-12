import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate, useLocation, Link } from "react-router";
import { Paperclip, Loader2, AlertCircle, Play, Info } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { MetadataBanner } from "@/components/metadataBanner";
import { useDebounce } from "@/hooks/useDebounce";
import { useSubscription } from "@/hooks/useSubscription";
import { useSupportedFormats } from "@/hooks/useSupportedFormats";
import { useApi } from "@/api";
import { cn } from "@/lib/utils";
import { AxiosError } from "axios";

const URL_REGEX = /^https?:\/\/[^\s.]+\.[^\s]{2,}/i;
const AI_TRANSFORM_STORAGE_KEY = "yapit-ai-transform-enabled";

const MAX_FILE_SIZE_MB = 100;
const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024;

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
  document_id: string | null;
  error: string | null;
  failed_pages: number[];
}

interface ExtractionAcceptedResponse {
  extraction_id: string;
  content_hash: string;
  total_pages: number;
}

interface DocumentCreateResponse {
  id: string;
  title: string | null;
  failed_pages: number[];
}

interface BatchSubmittedResponse {
  content_hash: string;
  total_pages: number;
  submitted_at: string;
}

type InputMode = "idle" | "text" | "url" | "file";
type UrlState = "detecting" | "loading" | "ready" | "error";

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
  const [batchMode, setBatchMode] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const dragCounterRef = useRef(0);
  const abortControllerRef = useRef<AbortController | null>(null);
  const prepareAbortRef = useRef<AbortController | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const extractionIdRef = useRef<string | null>(null);
  const navigate = useNavigate();
  const location = useLocation();
  const { api, isAnonymous } = useApi();
  const { tier } = useSubscription();
  const formats = useSupportedFormats();

  const debouncedValue = useDebounce(value, 400);

  const isUrl = useCallback((text: string) => URL_REGEX.test(text.trim()), []);

  /** Whether the prepare response needs user confirmation via MetadataBanner. */
  const needsBanner = (data: PrepareResponse): boolean => {
    if (data.endpoint === "website") return false;
    const fmt = formats?.formats[data.metadata.content_type];
    return !!fmt?.ai || (!!fmt?.has_pages && data.metadata.total_pages > 1);
  };

  // Pre-fill URL from catch-all route redirect (yapit.md/example.com/path)
  useEffect(() => {
    const state = location.state as { prefillUrl?: string } | null;
    if (state?.prefillUrl) {
      setValue(state.prefillUrl);
      window.history.replaceState({}, "", location.pathname);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps -- mount only

  // Reset all state when home button clicked while on home
  useEffect(() => {
    const handleReset = () => {
      abortControllerRef.current?.abort();
      abortControllerRef.current = null;
      prepareAbortRef.current?.abort();
      prepareAbortRef.current = null;
      if (pollTimerRef.current) {
        clearTimeout(pollTimerRef.current);
        pollTimerRef.current = null;
      }
      extractionIdRef.current = null;
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

    if (urlState === "loading" || urlState === "ready") return;
    if (mode === "file") return;

    if (isUrl(trimmed)) {
      setMode("url");
      setUrlState("detecting");
    } else if (mode !== "text") {
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

    prepareAbortRef.current?.abort();
    const controller = new AbortController();
    prepareAbortRef.current = controller;

    const fetchMetadata = async () => {
      setUrlState("loading");
      setError(null);
      setPrepareData(null);

      try {
        const response = await api.post<PrepareResponse>("/v1/documents/prepare", {
          url: debouncedValue.trim(),
        }, { signal: controller.signal });

        if (controller.signal.aborted) return;
        setPrepareData(response.data);

        if (needsBanner(response.data)) {
          setUrlState("ready");
        } else {
          await createDocument(response.data);
        }
      } catch (err) {
        if (controller.signal.aborted) return;
        setUrlState("error");
        if (err instanceof AxiosError && err.response) {
          const detail = err.response.data?.detail;
          setError(detail || err.message);
        } else {
          setError(err instanceof Error ? err.message : "Failed to fetch URL");
        }
      }
    };

    fetchMetadata();
  }, [debouncedValue, mode, isUrl, api]); // eslint-disable-line react-hooks/exhaustive-deps

  // Save AI Transform preference
  useEffect(() => {
    localStorage.setItem(AI_TRANSFORM_STORAGE_KEY, String(aiTransformEnabled));
  }, [aiTransformEnabled]);

  const createDocument = async (data: PrepareResponse, pages: number[] | null = null) => {
    setIsCreating(true);
    setCompletedPages([]);

    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    const fmt = formats?.formats[data.metadata.content_type];
    const useAiTransform = !!fmt?.ai && (!fmt.free || aiTransformEnabled);
    const useBatchMode = batchMode && useAiTransform;

    const endpoint = data.endpoint === "website"
      ? "/v1/documents/website"
      : "/v1/documents/document";
    const body = data.endpoint === "website"
      ? { hash: data.hash }
      : {
          hash: data.hash,
          pages: pages,
          ai_transform: useAiTransform,
          batch_mode: useBatchMode,
        };

    try {
      const response = await api.post(endpoint, body, {
        signal: abortController.signal,
      });
      abortControllerRef.current = null;

      if (response.status === 201) {
        const docData = response.data as DocumentCreateResponse;
        navigate(`/listen/${docData.id}`, {
          state: { documentTitle: docData.title },
        });
        return;
      }

      if (useBatchMode) {
        const batchData = response.data as BatchSubmittedResponse;
        navigate(`/batch/${batchData.content_hash}`, {
          state: {
            totalPages: batchData.total_pages,
            submittedAt: batchData.submitted_at,
            documentTitle: data.metadata.title || data.metadata.file_name,
          },
        });
        return;
      }

      // Async extraction — poll for completion
      const accepted = response.data as ExtractionAcceptedResponse;
      const requestedPages = pages ?? Array.from({ length: data.metadata.total_pages }, (_, i) => i);
      extractionIdRef.current = accepted.extraction_id;

      const FAST_POLL_MS = 300;
      const SLOW_POLL_MS = 1500;
      const FAST_POLL_COUNT = 5;
      let pollCount = 0;

      const poll = async () => {
        try {
          const statusResponse = await api.post<ExtractionStatusResponse>("/v1/documents/extraction/status", {
            extraction_id: accepted.extraction_id,
            content_hash: accepted.content_hash,
            ai_transform: useAiTransform,
            pages: requestedPages,
          });
          const statusData = statusResponse.data;
          setCompletedPages(statusData.completed_pages);

          if (statusData.document_id) {
            extractionIdRef.current = null;
            const failedPages = statusData.failed_pages ?? [];
            navigate(`/listen/${statusData.document_id}`, {
              state: {
                documentTitle: data.metadata.title || data.metadata.file_name,
                failedPages: failedPages.length > 0 ? failedPages : undefined,
              },
            });
            return;
          }

          if (statusData.error) {
            extractionIdRef.current = null;
            setIsCreating(false);
            setCompletedPages([]);
            setError(statusData.error);
            return;
          }
        } catch (err) {
          console.warn("Extraction status poll failed:", err);
        }

        pollCount++;
        const delay = pollCount < FAST_POLL_COUNT ? FAST_POLL_MS : SLOW_POLL_MS;
        pollTimerRef.current = setTimeout(poll, delay);
      };

      pollTimerRef.current = setTimeout(poll, FAST_POLL_MS);

    } catch (err) {
      abortControllerRef.current = null;
      setIsCreating(false);
      setCompletedPages([]);

      if (err instanceof AxiosError && err.code === "ERR_CANCELED") {
        return;
      }

      handleCreateError(err);
    }
  };

  const cancelExtraction = useCallback(async () => {
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    if (pollTimerRef.current) {
      clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    if (extractionIdRef.current) {
      try {
        await api.post("/v1/documents/extraction/cancel", {
          extraction_id: extractionIdRef.current,
        });
      } catch { /* best-effort */ }
      extractionIdRef.current = null;
    }
    setIsCreating(false);
    setCompletedPages([]);
  }, [api]);

  const handleTextSubmit = async (content?: string, title?: string) => {
    const text = content ?? value.trim();
    if (!text) return;
    setIsCreating(true);

    try {
      const response = await api.post<DocumentCreateResponse>("/v1/documents/text", {
        content: text,
        title: title ?? undefined,
      });
      navigate(`/listen/${response.data.id}`, {
        state: { documentTitle: response.data.title }
      });
    } catch (err) {
      setIsCreating(false);
      handleCreateError(err);
    }
  };

  // No useCallback — only used within this component, and wrapping it
  // would cause stale closures over createDocument's captured state.
  const uploadFile = async (file: File) => {
    setMode("file");
    setError(null);
    setValue(file.name);

    if (file.size > MAX_FILE_SIZE_BYTES) {
      setUrlState("error");
      setError(`File too large (${(file.size / 1024 / 1024).toFixed(1)} MB). Maximum size is ${MAX_FILE_SIZE_MB} MB.`);
      return;
    }

    // Text files: read client-side, POST to /text directly (no prepare round-trip)
    const isTextFile = (file.type.startsWith("text/") && !file.type.includes("html"))
      || /\.(txt|md|markdown)$/i.test(file.name);
    if (isTextFile) {
      const content = await file.text();
      const title = file.name.replace(/\.[^.]+$/, "");
      await handleTextSubmit(content, title);
      return;
    }

    // Cancel any in-flight prepare or extraction
    prepareAbortRef.current?.abort();
    if (isCreating) await cancelExtraction();
    const controller = new AbortController();
    prepareAbortRef.current = controller;

    setUrlState("loading");

    try {
      const formData = new FormData();
      formData.append("file", file);

      const response = await api.post<PrepareResponse>("/v1/documents/prepare/upload", formData, {
        headers: { "Content-Type": "multipart/form-data" },
        signal: controller.signal,
      });

      if (controller.signal.aborted) return;

      if (needsBanner(response.data)) {
        setPrepareData(response.data);
        setUrlState("ready");
      } else {
        await createDocument(response.data);
      }
    } catch (err) {
      if (controller.signal.aborted) return;
      setUrlState("error");
      setIsCreating(false);
      handleUploadError(err);
    }
  };

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

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    dragCounterRef.current = 0;

    const files = e.dataTransfer.files;
    if (files.length === 0) return;

    const file = files[0];
    if (formats) {
      const isSupported = file.type in formats.formats
        || /\.(txt|md|markdown)$/i.test(file.name); // extension fallback for text files
      if (!isSupported) {
        setError(`Unsupported file type: ${file.type || file.name.split('.').pop()}`);
        return;
      }
    }

    await uploadFile(file);
  };

  const handleAiTransformToggle = useCallback((enabled: boolean) => {
    setAiTransformEnabled(enabled);
    if (enabled) {
      setUsageLimitExceeded(false);
    }
  }, []);

  /** Extract user-facing error from API responses. */
  const handleCreateError = (err: unknown) => {
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
  };

  const handleUploadError = (err: unknown) => {
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
  };

  const showMetadataBanner = (mode === "url" || mode === "file") && urlState === "ready" && prepareData?.endpoint === "document";
  const showTextMode = mode === "text" || mode === "idle";
  const isLoadingUrl = (mode === "url" || mode === "file") && (urlState === "loading" || urlState === "detecting");
  const formatsLoaded = formats !== null;

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
          disabled={isCreating || !formatsLoaded}
        />

        <div className="absolute right-3 top-3 flex flex-col gap-2">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={() => fileInputRef.current?.click()}
            disabled={isCreating || isLoadingUrl || !formatsLoaded}
            className="h-10 w-10"
          >
            <Paperclip className="h-5 w-5" />
          </Button>
        </div>

        <input
          ref={fileInputRef}
          type="file"
          accept={formats?.accept ?? ""}
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
            {isAnonymous ? (
              <>
                <Link to="/handler/signin" className="text-primary hover:underline">Sign in</Link>
                {" for more storage or "}
                <Link to="/account" className="text-primary hover:underline">delete old documents</Link>.
              </>
            ) : tier === "free" ? (
              <>
                <Link to="/subscription" className="text-primary hover:underline">Upgrade</Link>
                {" for more storage or "}
                <Link to="/account" className="text-primary hover:underline">delete old documents</Link>.
              </>
            ) : (
              <>
                <Link to="/account" className="text-primary hover:underline">Delete old documents</Link>
                {" to free up space."}
              </>
            )}
          </span>
        </div>
      )}

      {showMetadataBanner && prepareData && formats && (
        <MetadataBanner
          metadata={prepareData.metadata}
          formatInfo={formats.formats[prepareData.metadata.content_type]}
          aiTransformEnabled={aiTransformEnabled}
          onAiTransformToggle={handleAiTransformToggle}
          batchMode={batchMode}
          onBatchModeToggle={setBatchMode}
          onConfirm={(pages) => createDocument(prepareData, pages)}
          onCancel={cancelExtraction}
          isLoading={isCreating}
          completedPages={completedPages}
          uncachedPages={prepareData.uncached_pages}
        />
      )}

      {showTextMode && value.trim() && (
        <Button
          onClick={() => handleTextSubmit()}
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

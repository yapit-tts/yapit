import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate } from "react-router";
import { Paperclip, Loader2, AlertCircle, Play } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { MetadataBanner } from "@/components/metadataBanner";
import { useDebounce } from "@/hooks/useDebounce";
import { useApi } from "@/api";
import { cn } from "@/lib/utils";

const URL_REGEX = /^https?:\/\/.+/i;
const OCR_STORAGE_KEY = "yapit-ocr-enabled";

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
  metadata: DocumentMetadata;
  endpoint: "text" | "website" | "document";
  credit_cost: string;
  uncached_pages: number[];
}

interface DocumentCreateResponse {
  id: string;
  title: string | null;
}

type InputMode = "idle" | "text" | "url";
type UrlState = "detecting" | "loading" | "ready" | "error";

export function UnifiedInput() {
  const [value, setValue] = useState("");
  const [mode, setMode] = useState<InputMode>("idle");
  const [urlState, setUrlState] = useState<UrlState>("detecting");
  const [prepareData, setPrepareData] = useState<PrepareResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [ocrEnabled, setOcrEnabled] = useState(() => {
    const stored = localStorage.getItem(OCR_STORAGE_KEY);
    return stored !== null ? stored === "true" : true;
  });

  const fileInputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const { api } = useApi();

  const debouncedValue = useDebounce(value, 400);

  const isUrl = useCallback((text: string) => URL_REGEX.test(text.trim()), []);

  // Detect input type and update mode
  useEffect(() => {
    const trimmed = value.trim();
    if (!trimmed) {
      setMode("idle");
      setPrepareData(null);
      setError(null);
      return;
    }

    if (isUrl(trimmed)) {
      setMode("url");
      setUrlState("detecting");
    } else {
      setMode("text");
      setPrepareData(null);
      setError(null);
    }
  }, [value, isUrl]);

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
        setError(err instanceof Error ? err.message : "Failed to fetch URL");
      }
    };

    fetchMetadata();
  }, [debouncedValue, mode, isUrl, api]);

  // Save OCR preference
  useEffect(() => {
    localStorage.setItem(OCR_STORAGE_KEY, String(ocrEnabled));
  }, [ocrEnabled]);

  const createDocument = async (data: PrepareResponse) => {
    setIsCreating(true);
    try {
      const endpoint = data.endpoint === "website"
        ? "/v1/documents/website"
        : "/v1/documents/document";

      const response = await api.post<DocumentCreateResponse>(endpoint, {
        hash: data.hash,
        use_ocr: data.endpoint === "document" ? ocrEnabled : undefined,
      });

      navigate("/playback", {
        state: {
          apiResponse: { id: response.data.id, title: response.data.title },
          inputText: value
        }
      });
    } catch (err) {
      setIsCreating(false);
      setError(err instanceof Error ? err.message : "Failed to create document");
    }
  };

  const handleTextSubmit = async () => {
    if (!value.trim()) return;
    setIsCreating(true);

    try {
      const response = await api.post<DocumentCreateResponse>("/v1/documents/text", {
        content: value.trim(),
      });
      navigate("/playback", {
        state: {
          apiResponse: response.data,
          inputText: value
        }
      });
    } catch (err) {
      setIsCreating(false);
      setError(err instanceof Error ? err.message : "Failed to create document");
    }
  };

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setMode("url");
    setUrlState("loading");
    setError(null);
    setValue(file.name);

    try {
      const formData = new FormData();
      formData.append("file", file);

      const response = await api.post<PrepareResponse>("/v1/documents/prepare/upload", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });

      setPrepareData(response.data);
      setUrlState("ready");
    } catch (err) {
      setUrlState("error");
      setError(err instanceof Error ? err.message : "Failed to upload file");
    }
  };

  const showMetadataBanner = mode === "url" && urlState === "ready" && prepareData?.endpoint === "document";
  const showTextMode = mode === "text" || mode === "idle";
  const isLoadingUrl = mode === "url" && (urlState === "loading" || urlState === "detecting");

  return (
    <div className="flex flex-col w-full max-w-2xl mx-auto gap-4">
      <div className="relative">
        <Textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Paste a URL, upload a file, or type text..."
          className={cn(
            "min-h-[120px] pr-12 resize-none transition-all",
            mode === "text" && "min-h-[200px]",
            error && "border-destructive"
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
            className="h-8 w-8"
          >
            <Paperclip className="h-4 w-4" />
          </Button>
        </div>

        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.docx,.doc,.txt,.html,.htm,.epub"
          onChange={handleFileSelect}
          className="hidden"
        />

        {isLoadingUrl && (
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

      {showMetadataBanner && prepareData && (
        <MetadataBanner
          metadata={prepareData.metadata}
          creditCost={prepareData.credit_cost}
          ocrEnabled={ocrEnabled}
          onOcrToggle={setOcrEnabled}
          onConfirm={() => createDocument(prepareData)}
          isLoading={isCreating}
        />
      )}

      {showTextMode && value.trim() && (
        <Button
          onClick={handleTextSubmit}
          disabled={isCreating}
          variant="secondary"
          className="self-start"
        >
          {isCreating ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Processing...
            </>
          ) : (
            <>
              <Play className="h-4 w-4" />
              Start Listening
            </>
          )}
        </Button>
      )}
    </div>
  );
}

import { useState, useMemo, useEffect, useRef } from "react";
import { FileText, Loader2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { FormatInfo } from "@/hooks/useSupportedFormats";

interface DocumentMetadata {
  content_type: string;
  total_pages: number;
  title: string | null;
  url: string | null;
  file_name: string | null;
  file_size: number | null;
}

interface MetadataBannerProps {
  metadata: DocumentMetadata;
  formatInfo: FormatInfo | undefined;
  aiTransformEnabled: boolean;
  onAiTransformToggle: (enabled: boolean) => void;
  batchMode: boolean;
  onBatchModeToggle: (enabled: boolean) => void;
  onConfirm: (pages: number[] | null) => void;
  onCancel?: () => void;
  isLoading: boolean;
  completedPages?: number[];
  uncachedPages?: number[];
  className?: string;
}

function formatFileSize(bytes: number | null): string {
  if (bytes === null) return "Unknown size";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Format cached pages as ranges for display.
 * Returns null if >3 ranges (too scattered to display nicely).
 * Input: 0-indexed page numbers, Output: 1-indexed display string.
 */
function formatCachedPages(totalPages: number, uncachedPages: number[]): string | null {
  const uncachedSet = new Set(uncachedPages);
  const cachedPages = Array.from({ length: totalPages }, (_, i) => i).filter(p => !uncachedSet.has(p));

  if (cachedPages.length === 0) return null;

  const ranges: [number, number][] = [];
  let rangeStart = cachedPages[0];
  let rangeEnd = cachedPages[0];

  for (let i = 1; i < cachedPages.length; i++) {
    if (cachedPages[i] === rangeEnd + 1) {
      rangeEnd = cachedPages[i];
    } else {
      ranges.push([rangeStart, rangeEnd]);
      rangeStart = cachedPages[i];
      rangeEnd = cachedPages[i];
    }
  }
  ranges.push([rangeStart, rangeEnd]);

  if (ranges.length > 3) return null;

  const rangeStrs = ranges.map(([start, end]) => {
    const s = start + 1;
    const e = end + 1;
    return s === e ? `${s}` : `${s}-${e}`;
  });

  return `Pages ${rangeStrs.join(", ")} free`;
}

/**
 * Parse page range string into array of page indices (0-indexed).
 * Input: "1-10, 25, 30-50" (1-indexed, user-facing)
 * Output: [0,1,2...9, 24, 29,30...49] (0-indexed, API)
 * Clamps to totalPages, deduplicates, sorts.
 */
function parsePageRanges(input: string, totalPages: number): number[] | null {
  const trimmed = input.trim();
  if (!trimmed) return null;

  const pages = new Set<number>();
  const parts = trimmed.split(",");

  for (const part of parts) {
    const rangePart = part.trim();
    if (!rangePart) continue;

    if (rangePart.includes("-")) {
      const [startStr, endStr] = rangePart.split("-").map(s => s.trim());
      const start = parseInt(startStr, 10);
      const end = parseInt(endStr, 10);

      if (isNaN(start) || isNaN(end)) continue;

      const clampedStart = Math.max(1, Math.min(start, totalPages));
      const clampedEnd = Math.max(1, Math.min(end, totalPages));
      const actualStart = Math.min(clampedStart, clampedEnd);
      const actualEnd = Math.max(clampedStart, clampedEnd);

      for (let i = actualStart; i <= actualEnd; i++) {
        pages.add(i - 1);
      }
    } else {
      const page = parseInt(rangePart, 10);
      if (isNaN(page)) continue;
      const clamped = Math.max(1, Math.min(page, totalPages));
      pages.add(clamped - 1);
    }
  }

  if (pages.size === 0) return null;
  return Array.from(pages).sort((a, b) => a - b);
}

/**
 * Visual bar showing selected pages and extraction progress.
 * Groups consecutive pages by visual state into proportional segments
 * (per-page divs break at high page counts due to sub-pixel rounding + border overflow).
 */
function PageSelectionBar({
  selectedPages,
  totalPages,
  completedPages = [],
  isProcessing = false,
}: {
  selectedPages: number[] | null;
  totalPages: number;
  completedPages?: number[];
  isProcessing?: boolean;
}) {
  type PageState = "unselected" | "completed" | "pending" | "selected";

  const segments = useMemo(() => {
    const selectedSet = new Set(selectedPages ?? Array.from({ length: totalPages }, (_, i) => i));
    const completedSet = new Set(completedPages);

    const getState = (i: number): PageState => {
      if (!selectedSet.has(i)) return "unselected";
      if (isProcessing && completedSet.has(i)) return "completed";
      if (isProcessing) return "pending";
      return "selected";
    };

    const result: { state: PageState; length: number }[] = [];
    let currentState = getState(0);
    let currentLength = 1;

    for (let i = 1; i < totalPages; i++) {
      const state = getState(i);
      if (state === currentState) {
        currentLength++;
      } else {
        result.push({ state: currentState, length: currentLength });
        currentState = state;
        currentLength = 1;
      }
    }
    result.push({ state: currentState, length: currentLength });

    return result;
  }, [selectedPages, totalPages, completedPages, isProcessing]);

  const stateClasses: Record<PageState, string> = {
    unselected: "bg-muted/20",
    completed: "bg-primary",
    pending: "bg-primary/30",
    selected: "bg-primary/60",
  };

  return (
    <div className="flex h-2 rounded-sm overflow-hidden bg-muted/30">
      {segments.map((segment, i) => (
        <div
          key={i}
          className={cn("min-w-0 transition-colors duration-300", stateClasses[segment.state])}
          style={{ flex: segment.length }}
        />
      ))}
    </div>
  );
}

export function MetadataBanner({
  metadata,
  formatInfo,
  aiTransformEnabled,
  onAiTransformToggle,
  batchMode,
  onBatchModeToggle,
  onConfirm,
  onCancel,
  isLoading,
  completedPages = [],
  uncachedPages = [],
  className,
}: MetadataBannerProps) {
  const [pageRangeInput, setPageRangeInput] = useState("");

  const title = metadata.title || metadata.file_name || "Untitled Document";
  const showPageSelector = !!formatInfo?.has_pages && metadata.total_pages > 1;
  const showAiToggle = !!formatInfo?.ai;
  const forceAi = !!formatInfo?.ai && !formatInfo?.free;
  const aiActive = forceAi || aiTransformEnabled;

  const selectedPages = useMemo(
    () => parsePageRanges(pageRangeInput, metadata.total_pages),
    [pageRangeInput, metadata.total_pages]
  );

  const effectivePageCount = selectedPages?.length ?? metadata.total_pages;
  const userOverrideBatch = useRef(false);

  useEffect(() => {
    userOverrideBatch.current = false;
  }, [metadata]);

  useEffect(() => {
    if (userOverrideBatch.current) return;
    onBatchModeToggle(effectivePageCount > 100);
  }, [effectivePageCount, onBatchModeToggle]);

  const handleBatchToggle = (enabled: boolean) => {
    userOverrideBatch.current = true;
    onBatchModeToggle(enabled);
  };

  const handleConfirm = () => {
    onConfirm(selectedPages);
  };

  return (
    <div
      className={cn(
        "rounded-lg border bg-card p-4 shadow-sm animate-in fade-in slide-in-from-top-2 duration-200",
        className
      )}
    >
      {/* Header: icon, title, metadata */}
      <div className="flex items-start gap-4">
        <div className="flex h-10 w-10 items-center justify-center rounded-md bg-primary/10 text-primary shrink-0">
          <FileText className="h-5 w-5" />
        </div>

        <div className="flex-1 min-w-0">
          <h3 className="font-medium truncate" title={title}>
            {title}
          </h3>
          <div className="flex items-center gap-3 text-sm text-muted-foreground mt-1">
            <span>{metadata.total_pages} {metadata.total_pages === 1 ? "page" : "pages"}</span>
            <span>·</span>
            <span>{formatFileSize(metadata.file_size)}</span>
            {aiActive && (() => {
              const cachedText = formatCachedPages(metadata.total_pages, uncachedPages);
              if (!cachedText) return null;
              return (
                <>
                  <span>·</span>
                  <span className="text-accent-success">{cachedText}</span>
                </>
              );
            })()}
          </div>
        </div>
      </div>

      {showPageSelector && (
        <div className="mt-4 space-y-2">
          <div className="flex items-center gap-3">
            <Label htmlFor="page-range" className="text-sm text-muted-foreground shrink-0">
              Pages
            </Label>
            <Input
              id="page-range"
              value={pageRangeInput}
              onChange={(e) => setPageRangeInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !isLoading && handleConfirm()}
              placeholder={`1-${metadata.total_pages}`}
              className="h-8 text-sm"
            />
          </div>
          <PageSelectionBar
            selectedPages={selectedPages}
            totalPages={metadata.total_pages}
            completedPages={completedPages}
            isProcessing={isLoading}
          />
        </div>
      )}

      {/* Footer: learn more, toggles, GO */}
      <div className="flex items-center justify-between mt-4">
        <a
          href="/tips#ai-transform"
          className="text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          Learn more
        </a>

        <div className="flex items-center gap-4">
          {aiActive && !isLoading && (
            <div className="flex items-center gap-2" title="Save 50% on tokens. May take minutes to hours.">
              <Switch
                id="batch-mode-toggle"
                checked={batchMode}
                onCheckedChange={handleBatchToggle}
              />
              <Label htmlFor="batch-mode-toggle" className="text-sm cursor-pointer">
                Batch
              </Label>
            </div>
          )}

          {showAiToggle && (
            <div className="flex items-center gap-2">
              <Switch
                id="ai-transform-toggle"
                checked={forceAi || aiTransformEnabled}
                onCheckedChange={onAiTransformToggle}
                disabled={forceAi}
              />
              <Label htmlFor="ai-transform-toggle" className="text-sm cursor-pointer">
                AI Transform
              </Label>
            </div>
          )}

          {isLoading ? (
            <div className="flex items-center gap-2">
              <Button variant="ghost" size="sm" onClick={onCancel} className="h-8 w-8 p-0">
                <X className="h-4 w-4" />
              </Button>
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Processing...
              </div>
            </div>
          ) : (
            <Button onClick={handleConfirm} size="sm">
              GO
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

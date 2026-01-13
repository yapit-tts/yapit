import { useState, useMemo } from "react";
import { FileText, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

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
  aiTransformEnabled: boolean;
  onAiTransformToggle: (enabled: boolean) => void;
  onConfirm: (pages: number[] | null) => void;
  isLoading: boolean;
  className?: string;
}

function formatFileSize(bytes: number | null): string {
  if (bytes === null) return "Unknown size";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Parse page range string into array of page indices (0-indexed).
 * Input: "1-10, 25, 30-50" (1-indexed, user-facing)
 * Output: [0,1,2...9, 24, 29,30...49] (0-indexed, API)
 * Clamps to totalPages, deduplicates, sorts.
 */
function parsePageRanges(input: string, totalPages: number): number[] | null {
  const trimmed = input.trim();
  if (!trimmed) return null; // empty = all pages

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

      // Clamp to valid range (1-indexed input, convert to 0-indexed)
      const clampedStart = Math.max(1, Math.min(start, totalPages));
      const clampedEnd = Math.max(1, Math.min(end, totalPages));
      const actualStart = Math.min(clampedStart, clampedEnd);
      const actualEnd = Math.max(clampedStart, clampedEnd);

      for (let i = actualStart; i <= actualEnd; i++) {
        pages.add(i - 1); // Convert to 0-indexed
      }
    } else {
      const page = parseInt(rangePart, 10);
      if (isNaN(page)) continue;
      const clamped = Math.max(1, Math.min(page, totalPages));
      pages.add(clamped - 1); // Convert to 0-indexed
    }
  }

  if (pages.size === 0) return null;
  return Array.from(pages).sort((a, b) => a - b);
}

/**
 * Visual bar showing selected pages.
 * Read-only, just reflects the current selection.
 */
function PageSelectionBar({
  selectedPages,
  totalPages
}: {
  selectedPages: number[] | null;
  totalPages: number;
}) {
  const selectedSet = useMemo(
    () => new Set(selectedPages ?? Array.from({ length: totalPages }, (_, i) => i)),
    [selectedPages, totalPages]
  );

  return (
    <div className="flex h-2 rounded-sm overflow-hidden bg-muted/30">
      {Array.from({ length: totalPages }, (_, i) => (
        <div
          key={i}
          className={cn(
            "flex-1 min-w-0",
            selectedSet.has(i) ? "bg-primary/60" : "bg-muted/20"
          )}
          style={{
            borderRight: i < totalPages - 1 ? "1px solid rgba(0,0,0,0.05)" : "none",
          }}
        />
      ))}
    </div>
  );
}

export function MetadataBanner({
  metadata,
  aiTransformEnabled,
  onAiTransformToggle,
  onConfirm,
  isLoading,
  className,
}: MetadataBannerProps) {
  const [pageRangeInput, setPageRangeInput] = useState("");

  const title = metadata.title || metadata.file_name || "Untitled Document";
  const isPdf = metadata.content_type === "application/pdf";
  const isMultiPage = metadata.total_pages > 1;

  const selectedPages = useMemo(
    () => parsePageRanges(pageRangeInput, metadata.total_pages),
    [pageRangeInput, metadata.total_pages]
  );

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
          </div>
        </div>
      </div>

      {/* Page selector (for multi-page PDFs) */}
      {isPdf && isMultiPage && (
        <div className="mt-4 space-y-2">
          <div className="flex items-center gap-3">
            <Label htmlFor="page-range" className="text-sm text-muted-foreground shrink-0">
              Pages
            </Label>
            <Input
              id="page-range"
              value={pageRangeInput}
              onChange={(e) => setPageRangeInput(e.target.value)}
              placeholder={`1-${metadata.total_pages}`}
              className="h-8 text-sm"
            />
          </div>
          <PageSelectionBar selectedPages={selectedPages} totalPages={metadata.total_pages} />
        </div>
      )}

      {/* Footer: learn more, toggle, GO */}
      <div className="flex items-center justify-between mt-4">
        <a
          href="/tips#ai-transform"
          className="text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          Learn more
        </a>

        <div className="flex items-center gap-4">
          {isPdf && (
            <div className="flex items-center gap-2">
              <Switch
                id="ai-transform-toggle"
                checked={aiTransformEnabled}
                onCheckedChange={onAiTransformToggle}
              />
              <Label htmlFor="ai-transform-toggle" className="text-sm cursor-pointer">
                AI Transform
              </Label>
            </div>
          )}

          <Button onClick={handleConfirm} disabled={isLoading} size="sm">
            {isLoading ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Processing...
              </>
            ) : (
              "GO"
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}

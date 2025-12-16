import { FileText, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
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
  creditCost: string;
  ocrEnabled: boolean;
  onOcrToggle: (enabled: boolean) => void;
  onConfirm: () => void;
  isLoading: boolean;
  className?: string;
}

function formatFileSize(bytes: number | null): string {
  if (bytes === null) return "Unknown size";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function MetadataBanner({
  metadata,
  creditCost,
  ocrEnabled,
  onOcrToggle,
  onConfirm,
  isLoading,
  className,
}: MetadataBannerProps) {
  const title = metadata.title || metadata.file_name || "Untitled Document";
  const isPdf = metadata.content_type === "application/pdf";

  return (
    <div
      className={cn(
        "rounded-lg border bg-card p-4 shadow-sm animate-in fade-in slide-in-from-top-2 duration-200",
        className
      )}
    >
      <div className="flex items-start gap-4">
        <div className="flex h-10 w-10 items-center justify-center rounded-md bg-primary/10 text-primary">
          <FileText className="h-5 w-5" />
        </div>

        <div className="flex-1 min-w-0">
          <h3 className="font-medium truncate" title={title}>
            {title}
          </h3>
          <div className="flex items-center gap-3 text-sm text-muted-foreground mt-1">
            <span>{metadata.total_pages} {metadata.total_pages === 1 ? "page" : "pages"}</span>
            <span>•</span>
            <span>{formatFileSize(metadata.file_size)}</span>
            {parseFloat(creditCost) > 0 && (
              <>
                <span>•</span>
                <span className="text-primary font-medium">{creditCost} credits</span>
              </>
            )}
          </div>
        </div>

        <div className="flex items-center gap-4">
          {isPdf && (
            <div className="flex items-center gap-2">
              <Switch
                id="ocr-toggle"
                checked={ocrEnabled}
                onCheckedChange={onOcrToggle}
              />
              <Label htmlFor="ocr-toggle" className="text-sm cursor-pointer">
                OCR
              </Label>
            </div>
          )}

          <Button onClick={onConfirm} disabled={isLoading} size="sm">
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

import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate, useLocation } from "react-router";
import { AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useApi } from "@/api";

interface BatchStatus {
  status: "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED" | "EXPIRED";
  submitted_at: string;
  total_pages: number;
  document_id: string | null;
  error: string | null;
}

interface LocationState {
  totalPages?: number;
  submittedAt?: string;
  documentTitle?: string;
}

const POLL_INTERVAL_MS = 5000;

const COZY_MESSAGES = [
  "Brewing your document...",
  "Good things take time ☕",
  "Still percolating...",
  "Pages are being processed...",
  "Almost there... maybe...",
];

function formatSubmittedTime(isoString: string): string {
  const date = new Date(isoString);
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export default function BatchStatusPage() {
  const { contentHash } = useParams<{ contentHash: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const { api } = useApi();

  const locationState = location.state as LocationState | null;

  const [status, setStatus] = useState<BatchStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cozyMessageIdx, setCozyMessageIdx] = useState(0);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const isTerminal = status?.status === "SUCCEEDED" || status?.status === "FAILED" || status?.status === "EXPIRED";

  // Poll for batch status
  useEffect(() => {
    if (!contentHash) return;

    const poll = async () => {
      try {
        const response = await api.get<BatchStatus>(`/v1/documents/batch/${contentHash}/status`);
        setStatus(response.data);
        setError(null);

        if (response.data.status === "SUCCEEDED" && response.data.document_id) {
          navigate(`/listen/${response.data.document_id}`, { replace: true });
        }
      } catch (err) {
        setError("Failed to check batch status");
      }
    };

    poll();
    pollRef.current = setInterval(poll, POLL_INTERVAL_MS);

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [contentHash, api, navigate]);

  // Stop polling on terminal state
  useEffect(() => {
    if (isTerminal && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, [isTerminal]);

  // Rotate cozy messages
  useEffect(() => {
    if (isTerminal) return;
    const interval = setInterval(() => {
      setCozyMessageIdx((i) => (i + 1) % COZY_MESSAGES.length);
    }, 8000);
    return () => clearInterval(interval);
  }, [isTerminal]);

  const title = locationState?.documentTitle || "Your document";
  const totalPages = status?.total_pages || locationState?.totalPages;
  const submittedAt = status?.submitted_at || locationState?.submittedAt;

  const isFailed = status?.status === "FAILED" || status?.status === "EXPIRED";

  return (
    <div className="flex flex-col items-center justify-center w-full px-4 py-16 max-w-lg mx-auto">
      <div className="w-full space-y-6 text-center">
        {/* Title */}
        <div>
          <h1 className="text-xl font-medium truncate" title={title}>{title}</h1>
          {totalPages && (
            <p className="text-sm text-muted-foreground mt-1">
              {totalPages} {totalPages === 1 ? "page" : "pages"}
            </p>
          )}
        </div>

        {/* Status area — placeholder for creative loading animation */}
        {!isFailed && (
          <div className="py-12">
            <p className="text-lg text-muted-foreground">
              {COZY_MESSAGES[cozyMessageIdx]}
            </p>
            {submittedAt && (
              <p className="text-sm text-muted-foreground/60 mt-2">
                Submitted at {formatSubmittedTime(submittedAt)}
              </p>
            )}
          </div>
        )}

        {/* Error state */}
        {isFailed && (
          <div className="py-8 space-y-4">
            <div className="flex items-center justify-center gap-2 text-destructive">
              <AlertCircle className="h-5 w-5" />
              <span className="font-medium">
                {status?.status === "EXPIRED" ? "Batch job expired" : "Batch processing failed"}
              </span>
            </div>
            {status?.error && (
              <p className="text-sm text-muted-foreground">{status.error}</p>
            )}
            <Button variant="secondary" onClick={() => navigate("/")}>
              Try again
            </Button>
          </div>
        )}

        {/* API error */}
        {error && !isFailed && (
          <p className="text-sm text-destructive">{error}</p>
        )}
      </div>
    </div>
  );
}
